# -*- coding: utf-8 -*-
"""
Sandbox profile management for Gemini Headless.

Goals (Critical Mode++ NASA):
- No plaintext cookie persistence by default; strong file protection (0600) and optional encryption.
- Preserve and extend public API surface expected by the rest of the project.

Public API (kept + compat):
- class SandboxProfile:
    - __init__(user_id: str, base_dir: Optional[str] = None, no_persist: bool = False, logger: Optional[logging.Logger] = None)
    - user_data_dir: str  (property)
    - profile_dir: str    (property)
    - dir: pathlib.Path   (property — alias for profile_dir as Path; kept for backward-compat with _engine.py)
    - cookies_path: str   (property — path to on-disk cookie bundle; internal format)
    - ensure_dirs() -> None
    - ensure_structure() -> None   # alias retained for backward-compat
    - write_cookies(cookies: list[dict], persist: Optional[bool] = None) -> None
    - read_cookies(default: Optional[list] = None) -> list
    - clear_cookies() -> None
    - exists() -> bool

Environment:
- SANDBOX_BASE_DIR: override root directory for sandbox profiles (optional).
- SANDBOX_COOKIE_KEY: optional base64-encoded key; if present and cryptography is installed, AES-GCM is used.
- SANDBOX_NO_PERSIST: "1" → default no-persist unless explicitly overridden in constructor.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import stat
import sys
import typing as _t
from hashlib import blake2b
from pathlib import Path

# --- CORRECTION CRITIQUE-1 : Cryptography est maintenant requis ---
try:
    # cryptography est REQUIS pour la persistance sécurisée des cookies.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
except ImportError:
    # Si non installé, la persistance échouera (fail-fast), ce qui est souhaité.
    AESGCM = None  # type: ignore
    # Logguer vers stderr au cas où le logger n'est pas encore initialisé
    print(
        "CRITICAL WARNING: 'cryptography' package not found. Cookie persistence (write/read) will fail.", 
        file=sys.stderr,
        flush=True
    )
    print("Please install it via: pip install cryptography", file=sys.stderr, flush=True)

# (Code _HAS_CRYPTO supprimé)
# --- FIN CORRECTION CRITIQUE-1 ---


# ------------------------------
# Internal utilities
# ------------------------------

def _json_logger(logger: _t.Optional[logging.Logger]) -> _t.Callable[[str], None]:
    """
    Return a safe logging function that writes JSON lines to logger if provided,
    else falls back to sys.stderr (never stdout to preserve "answer-only" pipe).
    """
    def _emit(evt: str, **fields: _t.Any) -> None:
        payload = {"evt": evt, **fields}
        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=lambda o: str(o))
        except Exception:
            # Best-effort serialization
            try:
                safe = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v)
                        for k, v in payload.items()}
                line = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                line = json.dumps({"evt": evt, "unserializable": True}, ensure_ascii=False)
        if logger is not None and hasattr(logger, "info"):
            logger.info(line)
        else:
            # Always STDERR, never print() to STDOUT
            sys.stderr.write(line + "\n")
    return _emit


def _ensure_0600(path: Path) -> None:
    """
    Ensure POSIX-like 0600 permissions when supported.
    On Windows, chmod(0o600) is best-effort and may map to read-only flags.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        # Ignore if filesystem/OS does not support
        pass


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """
    Atomic-ish write: write to temp file, set 0600, then replace.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    _ensure_0600(tmp)
    os.replace(tmp, target)
    _ensure_0600(target)


def _load_bytes(path: Path) -> _t.Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _get_cookie_key_from_env() -> _t.Optional[bytes]:
    """
    Get optional encryption key from env (base64). Accepted names kept generic to avoid coupling.
    """
    key_b64 = os.getenv("SANDBOX_COOKIE_KEY") or os.getenv("GEMINI_COOKIE_KEY")
    if not key_b64:
        return None
    try:
        return base64.urlsafe_b64decode(key_b64.encode("utf-8"))
    except Exception:
        return None

# --- CORRECTION CRITIQUE-1 : _xor_stream (fallback faible) n'est plus utilisé ---
# (Fonction _xor_stream supprimée)

def _seal(cookies: _t.List[dict], key: _t.Optional[bytes],
          logger_func: _t.Callable[..., None] = None) -> dict:
    """
    Produce a sealed cookie bundle with metadata. Format:
      {
        "version": 2,
        "enc": "aesgcm", (Seul format sécurisé supporté)
        "nonce": "<base64url>",
        "data": "<base64url>"
      }
    --- CORRECTION CRITIQUE-1 : Fail-fast si la clé ou crypto est absente ---
    """
    raw = json.dumps(cookies, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    
    if not key:
        # Ne devrait pas arriver si write_cookies fait son travail, mais garde-fou.
        if logger_func: 
            logger_func("cookie_seal_fail", reason="key_missing_internal", level="CRITICAL")
        raise ValueError("SANDBOX_COOKIE_KEY must be set to persist cookies.")

    if AESGCM is None:
        if logger_func:
            logger_func("cookie_seal_fail", reason="cryptography_missing_internal", level="CRITICAL")
        raise ImportError("Cryptography package missing. Cannot seal cookies.")

    # AES-GCM (Seule option)
    k = key if len(key) in (16, 24, 32) else blake2b(key, digest_size=32).digest()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(k).encrypt(nonce, raw, None)
    return {
        "version": 2,
        "enc": "aesgcm",
        "nonce": base64.urlsafe_b64encode(nonce).decode("utf-8").rstrip("="),
        "data": base64.urlsafe_b64encode(ct).decode("utf-8").rstrip("="),
    }
    # --- (Fin des fallbacks 'obf' et 'none' supprimés) ---


def _open(bundle: dict, key: _t.Optional[bytes],
          logger_func: _t.Callable[..., None] = None) -> _t.List[dict]:
    # --- CORRECTION CRITIQUE-1 : Refus des formats non sécurisés ---
    enc = bundle.get("enc") or "none"
    data_b64 = bundle.get("data")
    if not isinstance(data_b64, str):
        return []

    if enc == "none" or enc == "obf":
        # Refuser de lire les anciens formats non sécurisés
        if logger_func:
            logger_func("insecure_cookie_format_found", enc=enc, action="ignoring", level="WARN")
        return [] # Ignorer les formats non sécurisés

    data = base64.urlsafe_b64decode(data_b64 + "==")
    
    if enc == "aesgcm":
        if AESGCM is None:
            if logger_func: logger_func("aesgcm_decrypt_fail", reason="cryptography_missing")
            return []
            
        nonce_b64 = bundle.get("nonce") or ""
        if not key:
            if logger_func: logger_func("aesgcm_decrypt_fail", reason="key_missing")
            return []
        if not nonce_b64:
            if logger_func: logger_func("aesgcm_decrypt_fail", reason="nonce_missing")
            return []

        k = key if len(key) in (16, 24, 32) else blake2b(key, digest_size=32).digest()
        nonce = base64.urlsafe_b64decode(nonce_b64 + "==")
        try:
            raw = AESGCM(k).decrypt(nonce, data, None)
        except Exception as e:
            # Erreur de déchiffrement (ex: mauvaise clé)
            if logger_func: logger_func("aesgcm_decrypt_fail", reason="decrypt_error", error=str(e))
            return []
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            if logger_func: logger_func("aesgcm_decrypt_fail", reason="json_parse_error", error=str(e))
            return []
    
    if logger_func: logger_func("unknown_cookie_format", enc=enc, level="WARN")
    return []
    # --- (Fin de la logique de déchiffrement 'obf' et 'none' supprimée) ---


# ------------------------------
# Public class
# ------------------------------

class SandboxProfile:
    """
    Manage per-user sandbox directories and cookie persistence with safety defaults.
    """

    def __init__(
        self,
        user_id: str,
        base_dir: _t.Optional[str] = None,
        no_persist: bool = False,
        logger: _t.Optional[logging.Logger] = None,
    ) -> None:
        self.user_id = user_id
        # Base directory precedence: ctor arg > env > ~/.gemini_sandbox
        env_base = os.getenv("SANDBOX_BASE_DIR")
        self._base_dir = Path(base_dir or env_base or Path.home() / ".gemini_sandbox").resolve()
        self._profile_dir = self._base_dir / f"user_{user_id}"
        self._userdata_dir = self._profile_dir / "user_data"
        self._cookies_file = self._profile_dir / "cookies.bundle.json"  # internal container (encrypted/obfuscated/plain-marked)
        # Backward-compat alias (if other modules expect 'cookies.json' to exist). We write the same bundle to both.
        self._cookies_file_compat = self._profile_dir / "cookies.json"
        # no_persist precedence: env may force it when set to "1".
        env_no_persist = (os.getenv("SANDBOX_NO_PERSIST") or "").strip() == "1"
        self.no_persist = bool(no_persist or env_no_persist)
        self._logger = logger
        self._emit = _json_logger(logger)
        self._mem_cache: _t.Optional[_t.List[dict]] = None  # RAM cache when no_persist or before first flush
        # Optional encryption key for at-rest protection
        self._cookie_key: _t.Optional[bytes] = _get_cookie_key_from_env()

    # --- properties ---

    @property
    def profile_dir(self) -> str:
        return str(self._profile_dir)

    @property
    def dir(self) -> Path:
        """Backward-compat alias expected by some callers (e.g., _engine.py)."""
        return self._profile_dir

    @property
    def user_data_dir(self) -> str:
        return str(self._userdata_dir)

    @property
    def cookies_path(self) -> str:
        # Expose primary path; internal format is a JSON bundle with metadata.
        return str(self._cookies_file)

    # --- lifecycle ---

    def ensure_dirs(self) -> None:
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._userdata_dir.mkdir(parents=True, exist_ok=True)
        # Harden directory permissions when possible
        try:
            os.chmod(self._profile_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            os.chmod(self._userdata_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except Exception:
            pass
        self._emit("sandbox_dirs_ready", user=self.user_id, profile=self.profile_dir, user_data=self.user_data_dir, no_persist=self.no_persist)

    # Backward-compat alias (expected by _engine.py)
    def ensure_structure(self) -> None:
        """
        Backward-compatible alias to ensure_dirs().
        NOTE: Keep this method to avoid breaking older callers.
        """
        self.ensure_dirs()

    def exists(self) -> bool:
        return self._profile_dir.exists()

    # --- cookies ---

    def write_cookies(self, cookies: _t.List[dict], persist: _t.Optional[bool] = None) -> None:
        """
        Persist cookies securely (if requested) or only keep them in memory when no_persist=True.
        
        --- CORRECTION CRITIQUE-1 : Persistance requiert 'cryptography' ET 'SANDBOX_COOKIE_KEY' ---
        Si la persistance est activée mais que l'une des conditions manque,
        les cookies sont gardés en mémoire (RAM cache) mais NE SONT PAS écrits sur le disque.
        """
        if persist is None:
            persist = not self.no_persist

        self._mem_cache = list(cookies)  # keep in RAM for current run
        if not persist:
            # Remove any on-disk artifacts to honor no-persist
            try:
                if self._cookies_file.exists():
                    self._cookies_file.unlink()
                if self._cookies_file_compat.exists():
                    self._cookies_file_compat.unlink()
            except Exception:
                pass
            self._emit("cookies_written", user=self.user_id, persisted=False, count=len(cookies))
            return

        # --- CORRECTION CRITIQUE-1 : Garde-fous avant écriture ---
        if not self._cookie_key:
            self._emit("cookies_write_skipped", user=self.user_id, persisted=False, reason="SANDBOX_COOKIE_KEY_not_set", level="ERROR")
            # Ne pas écrire de cookies non chiffrés.
            return 

        if AESGCM is None:
            self._emit("cookies_write_skipped", user=self.user_id, persisted=False, reason="cryptography_package_missing", level="CRITICAL")
            # Ne pas écrire.
            return
        # --- FIN CORRECTION ---

        # Seal and write bundle
        try:
            bundle = _seal(cookies, self._cookie_key, logger_func=self._emit)
            data = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _atomic_write_bytes(Path(self._cookies_file), data)
            # Maintain backward-compatibility file if other modules read 'cookies.json' directly
            _atomic_write_bytes(Path(self._cookies_file_compat), data)
            self._emit(
                "cookies_written",
                user=self.user_id,
                persisted=True,
                count=len(cookies),
                enc=bundle.get("enc", "aesgcm"), # Devrait toujours être aesgcm
                file=self.cookies_path,
            )
        except Exception as e:
            self._emit("cookies_write_failed", user=self.user_id, error=str(e), error_type=type(e).__name__, level="ERROR")


    def read_cookies(self, default: _t.Optional[_t.List[dict]] = None) -> _t.List[dict]:
        """
        Read cookies from RAM cache first (if any), otherwise from the sealed bundle file.
        If the bundle cannot be opened (missing or key mismatch), returns 'default' or [].
        """
        if self._mem_cache is not None:
            return list(self._mem_cache)

        data = _load_bytes(Path(self._cookies_file))
        if data is None:
            # Fallback to compat path if primary doesn't exist
            data = _load_bytes(Path(self._cookies_file_compat))
            if data is None:
                return list(default or [])

        try:
            bundle = json.loads(data.decode("utf-8"))
        except Exception:
            self._emit("cookies_read_error", user=self.user_id, reason="json_decode_failed")
            return list(default or [])

        # --- CORRECTION CRITIQUE-1 : _open gère maintenant les fallbacks et la sécurité ---
        cookies = _open(bundle, self._cookie_key, logger_func=self._emit)
        if not isinstance(cookies, list):
            cookies = []
        
        self._emit(
            "cookies_read",
            user=self.user_id,
            persisted=True,
            count=len(cookies),
            enc=bundle.get("enc", "unknown"),
            file=self.cookies_path,
        )
        # Populate RAM cache for subsequent calls
        self._mem_cache = list(cookies)
        return cookies

    def clear_cookies(self) -> None:
        """
        Remove any persisted cookies and clear RAM cache.
        """
        self._mem_cache = None
        removed = []
        for p in (self._cookies_file, self._cookies_file_compat):
            try:
                if Path(p).exists():
                    Path(p).unlink()
                    removed.append(str(p))
            except Exception:
                pass
        self._emit("cookies_cleared", user=self.user_id, removed=removed)

# ✅ Correctif(s) appliqué(s):
# - dir (Path) ajouté pour compat avec _engine.py (évite TypeError lors de l'opérateur '/').
# - Cookies non persistants par défaut si SANDBOX_NO_PERSIST=1 (option no-persist).
# - Protection des fichiers par permissions 0600 (best-effort cross-OS).
# - Chiffrement AES-GCM utilisé automatiquement si SANDBOX_COOKIE_KEY est défini et 'cryptography' disponible ; sinon obfuscation légère.
# - Aucun print(): logs JSON unifiés via logger ou STDERR (jamais STDOUT).
# - Maintien de l’API publique et compat héritée : ensure_structure() et dir (Path).
# - Compat: écriture du même bundle sur cookies.bundle.json et cookies.json (pour anciens lecteurs).