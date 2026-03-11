# gemini_headless/collect/producers/be.py
# ✅ PATCH APPLIQUÉ : Robustesse du Parsing BatchExecute (Navigation Structurelle)
# - Ajout de _find_rpc_payload pour la recherche agnostique.
# - Mise à jour de _try_decode_batchexecute_to_text.
# - Maintien des fonctionnalités existantes (V14 parser, Agrégation, etc.).
#
# 🚀 INTELLIGENCE ADDITIONNELLE (PATTERN LEARNING & PERSISTENCE) :
# - Mémorisation de la méthode de parsing gagnante (_LAST_SUCCESSFUL_METHOD).
# - Réorganisation dynamique des tentatives de parsing pour prioriser le succès probable.
# - [NOUVEAU] Persistance sur disque (Cache) pour "mémoire musculaire" entre les sessions.

from __future__ import annotations
import asyncio
import json
import re
import time
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple, Set
from playwright.async_api import Page, Response
from urllib.parse import urlparse, parse_qs

# --- Imports pour les Patches ---
import json as _json
import re as _re

try:
    from ..utils.logs import jlog
except ImportError:
    def jlog(*_a, **_k): pass

# ============================================================================
# ✅ FIX V9.0-SECONDARY-001: Gestion des newlines dans les réponses Gemini
# ============================================================================

import re as _re_newline_handler

def _escape_newlines_in_json(text: str) -> str:
    """
    Échappe les newlines réelles (\n) à l'intérieur des valeurs JSON
    pour permettre le parsing JSON valide.
    """
    def escape_inside_quotes(match):
        inside = match.group(1)
        inside = inside.replace('\n', '\\n')
        inside = inside.replace('\r', '\\r')
        inside = inside.replace('\t', '\\t')
        inside = inside.replace('"', '\\"')
        return f'"{inside}"'
    
    pattern = r'"([^"]*(?:\n[^"]*)*)"'
    result = _re_newline_handler.sub(pattern, escape_inside_quotes, text)
    return result

# ============================================================================
# --- DEBUT PATCH: Helpers batchexecute (be.py) ---
# ============================================================================

_XSSI_PREFIX = ")]}'"
_LEN_LINE_RE = _re.compile(r'(?m)^(\d+)\n')

def _strip_xssi_prefix(body: str) -> str:
    if not body:
        return body
    if body.startswith(_XSSI_PREFIX):
        nl = body.find('\n')
        return body[nl+1:] if nl != -1 else ''
    return body

def _split_bex_segments(body: str) -> list[str]:
    """Découpe body en segments length+json selon le format Google batchexecute."""
    segments = []
    i = 0
    while i < len(body):
        m = _LEN_LINE_RE.search(body, i)
        if not m:
            break
        try:
            seg_len = int(m.group(1))
        except ValueError:
            break 
            
        start = m.end()
        end = start + seg_len
        if end > len(body):
            break
        segments.append(body[start:end])
        i = end
    return segments

def _json_loads_safe(s: str):
    try:
        return _json.loads(s)
    except Exception:
        return None

def _json_loads_multi(s: str, max_depth: int = 3):
    """Tente de parser des JSON stringifiés plusieurs fois."""
    cur = s
    for _ in range(max_depth):
        obj = _json_loads_safe(cur)
        if isinstance(obj, (dict, list)):
            return obj
        if isinstance(cur, str):
            cur = cur.strip().strip('"')
            cur = cur.replace('\\"', '"').replace('\\\\n', '\n')
        else:
            break
    return None

def _extract_known_gemini_paths(obj) -> list[str]:
    """Extrait le texte des chemins JSON connus de Gemini."""
    out = []
    try:
        cands = obj.get("candidates") if isinstance(obj, dict) else None
        if isinstance(cands, list):
            for c in cands:
                parts = ((((c or {}).get("content") or {}).get("parts")) or [])
                if isinstance(parts, list):
                    for p in parts:
                        t = (p or {}).get("text")
                        if isinstance(t, str) and len(t.strip()) >= 5:
                            out.append(t.strip())
                            
        for k in ("markdown", "text", "html", "answer"):
            v = obj.get(k) if isinstance(obj, dict) else None
            if isinstance(v, str) and len(v.strip()) >= 5:
                out.append(v.strip())
                
        blocks = obj.get("blocks") if isinstance(obj, dict) else None
        if isinstance(blocks, list):
            for b in blocks:
                t = (b or {}).get("text")
                if isinstance(t, str) and len(t.strip()) >= 5:
                    out.append(t.strip())
    except Exception:
        pass
    return out

def _deep_collect_strings(obj, out: list[str], *, min_len: int = 12, max_len: int = 2000):
    """Récupère récursivement des chaînes plausibles depuis un objet JSON."""
    NEG_PAT = ('wrb.fr', 'batchexecute', 'PCck7e', 'ESY5D', 'af.httprm', 'XSRF_TOKEN', 'f.req')
    
    if obj is None:
        return
        
    try:
        if isinstance(obj, str):
            s = obj.strip()
            if min_len <= len(s) <= max_len and not any(t in s for t in NEG_PAT):
                if s not in out:
                    out.append(s)
            return

        if isinstance(obj, (list, tuple)):
            for it in obj:
                _deep_collect_strings(it, out, min_len=min_len, max_len=max_len)
            return

        if isinstance(obj, dict):
            for k, v in obj.items():
                _deep_collect_strings(k, out, min_len=min_len, max_len=max_len)
                _deep_collect_strings(v, out, min_len=min_len, max_len=max_len)
    except Exception:
        pass

# ✅ PATCH: Fonction de navigation structurelle (Remplace la logique rigide)
def _find_rpc_payload(data: Any, target_rpcid: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    Recherche agnostique de la structure [RPCID, PAYLOAD] dans un arbre JSON arbitraire.
    Ne dépend plus des indices fixes (ex: cur[2]).
    Retourne une liste de tuples (rpcid, payload).
    """
    found_payloads = []
    
    if isinstance(data, list):
        # Heuristique forte: Une entrée RPC valide est souvent une liste contenant "wrb.fr"
        # Structure typique: ["wrb.fr", "RPCID", "JSON_STRING", ...]
        if len(data) >= 3 and data[0] == "wrb.fr" and isinstance(data[2], str):
            rpcid = data[1]
            payload = data[2]
            if target_rpcid is None or rpcid == target_rpcid:
                found_payloads.append((rpcid, payload))
        
        # Récursion pour trouver des RPC imbriqués
        for item in data:
            found_payloads.extend(_find_rpc_payload(item, target_rpcid))
            
    elif isinstance(data, dict):
        for value in data.values():
            found_payloads.extend(_find_rpc_payload(value, target_rpcid))
            
    return found_payloads

# === DEBUT PATCH (MISE À JOUR _try_decode_batchexecute_to_text) ===
def _try_decode_batchexecute_to_text(body: str) -> tuple[str, dict]:
    """
    Décode le body batchexecute et retourne (candidate_text, meta).
    Cherche des entrées ["wrb.fr", RPCID, payload_json_str, ...] via recherche structurelle.
    """
    meta = {"segments": 0, "rpcids": {}, "strings": 0}
    text_segments: list[str] = []
    
    bex = _strip_xssi_prefix(body)
    segments = _split_bex_segments(bex)
    meta["segments"] = len(segments)

    for seg in segments:
        arr = _json_loads_safe(seg)
        if not isinstance(arr, list):
            continue
            
        # ✅ PATCH: Utilisation de la recherche agnostique sur le segment décodé
        payloads = _find_rpc_payload(arr)
        
        for rpcid, payload_str in payloads:
            # Mise à jour des stats RPCID (nécessaire pour l'agrégation)
            meta["rpcids"][rpcid] = meta["rpcids"].get(rpcid, 0) + 1
            
            # Tentative de parsing du payload
            inner = _json_loads_multi(payload_str, max_depth=3)
            if inner is not None:
                # 1) Extraire des chemins Gemini connus
                knowns = _extract_known_gemini_paths(inner)
                for s in knowns:
                    if s not in text_segments: text_segments.append(s)
                
                # 2) Collecte profonde (deep collect) en secours
                _deep_collect_strings(inner, text_segments, min_len=10)

    meta["strings"] = len(text_segments)
    candidate = " ".join(s for s in text_segments if s).strip()
    return candidate, meta
# === FIN PATCH (MISE À JOUR _try_decode_batchexecute_to_text) ===

# ============================================================================
# ✅ PATCH V15.2 - DETECT GENUINE GEMINI RESPONSE
# ============================================================================

GEMINI_SIGNATURES_V15_2 = ["titre", "description", "TikTok", "audio", "transcript", "transcription", "contenu", "vidéo"]

def _is_likely_gemini_v15_2_strict(text: str) -> Tuple[bool, str]:
    if not text or len(text) < 80:
        return False, "too_short_strict"
    
    low = text.lower()
    
    sig_count = sum(1 for sig in GEMINI_SIGNATURES_V15_2 if sig.lower() in low)
    has_titre = ("\"titre\"" in low) or ("\"title\"" in low)
    has_desc = "\"description\"" in low
    ends_ok = low.rstrip().endswith("<>") or low.rstrip().endswith("<<end>>")
    
    if (has_titre and has_desc) or (sig_count >= 2 and ends_ok):
        return True, f"signatures={sig_count}"
        
    return False, "structure_missing"

def _is_likely_gemini_v15_2(text: str) -> Tuple[bool, str]:
    if not text or len(text) < 40:
        return False, "too_short"
    
    signature_count = sum(
        1 for sig in GEMINI_SIGNATURES_V15_2
        if sig.lower() in text.lower()
    )
    
    if signature_count >= 2:
        return True, f"signatures_{signature_count}"
    
    if '{"titre"' in text or '"titre"' in text:
        if '"description"' in text:
            return True, "json_valid"
    
    line_count = len(text.split('\n'))
    if line_count >= 3:
        return True, f"multiline_{line_count}"
    
    return False, "no_signatures"

# ============================================================================
# INTELLIGENT PARSER V14 - AVEC PATCH BEX + INTELLIGENCE PATTERN LEARNING + PERSISTENCE
# ============================================================================

# Variable globale module-level pour mémoriser la stratégie gagnante
_LAST_SUCCESSFUL_METHOD_NAME: Optional[str] = None

# --- INTELLIGENCE : CACHE PERSISTANT ---
_CACHE_FILE = os.path.join(tempfile.gettempdir(), ".gemini_headless_be_cache.json")

def _load_successful_method_from_cache():
    """Charge la dernière méthode gagnante depuis le disque (validité 24h)."""
    global _LAST_SUCCESSFUL_METHOD_NAME
    try:
        if not os.path.exists(_CACHE_FILE): return
        
        with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        timestamp = data.get('ts', 0)
        method = data.get('method')
        
        # Validité de 24h pour s'adapter aux changements de Google
        if method and (time.time() - timestamp < 86400):
            _LAST_SUCCESSFUL_METHOD_NAME = method
            jlog("be_cache_loaded", method=method, age_h=round((time.time()-timestamp)/3600, 1), level="DEBUG")
    except Exception as e:
        jlog("be_cache_load_error", error=str(e), level="DEBUG")

def _save_successful_method_to_cache(method_name: str):
    """Sauvegarde la méthode gagnante pour les futurs runs."""
    try:
        payload = {"method": method_name, "ts": time.time()}
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except Exception:
        pass

# Initialisation au chargement du module
_load_successful_method_from_cache()


async def parse_gemini_response_intelligent_v14(
    raw_response: str,
    attempt: int = 1,
    max_attempts: int = 3,
    debug: bool = True,
    validate_gemini_signatures: bool = True,
    allow_raw_fallback: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Parse REAL Gemini format - (V14 + BEX Decode Patch + Pattern Learning + Persistence).
    """
    global _LAST_SUCCESSFUL_METHOD_NAME
    import json
    import re
    
    jlog('parse_v14_start', attempt=attempt, response_len=len(raw_response), preferred_method=_LAST_SUCCESSFUL_METHOD_NAME)
    
    if not raw_response or not isinstance(raw_response, str):
        jlog('parse_v14_invalid_input')
        return None

    # Vérifie si la réponse ressemble à du batchexecute
    looks_bex = raw_response.startswith(_XSSI_PREFIX) or ("wrb.fr" in raw_response) or ("batchexecute" in raw_response)
    
    source_text = raw_response
    used_bex_decode = False

    if looks_bex:
        cand, meta = _try_decode_batchexecute_to_text(raw_response)
        jlog("parse_v14_bex_decode", 
             segments=meta.get("segments", 0), 
             rpcids=list(meta.get("rpcids", {}).keys())[:5], 
             strings=meta.get("strings", 0), 
             cand_len=len(cand))
        
        if len(cand) >= 40:
            source_text = cand
            used_bex_decode = True
        else:
            pass 

    if validate_gemini_signatures:
        is_likely_genuine, reason = _is_likely_gemini_v15_2_strict(source_text)
        
        if not is_likely_genuine:
            jlog('parse_v15_2_rejected_not_gemini_strict', 
                response_len=len(source_text),
                reason=reason,
                is_decoded_bex=used_bex_decode,
                level="WARN")
            return None
    
    raw_response_escaped = _escape_newlines_in_json(source_text)
    
    # --- DEFINITION DES STRATÉGIES DE PARSING ---
    # Pour permettre le re-ordering dynamique, on définit les méthodes ici.

    def _method_regex_direct():
        pattern = r'\{[^{}]*"titre"\s*:\s*"([^"]*)"[^{}]*"description"\s*:\s*"([^"]*)"\s*\}'
        match = re.search(pattern, raw_response_escaped, re.DOTALL)
        if match:
            titre_raw = match.group(1)
            desc_raw = match.group(2)
            titre = (titre_raw.replace('\\"', '"').replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t').replace('\\/', '/').strip())
            description = (desc_raw.replace('\\"', '"').replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t').replace('\\/', '/').strip())
            return {
                'titre': titre,
                'description': description,
                '_method': 'regex_direct_v9_escaped',
                '_attempt': attempt
            }
        return None

    def _method_regex_flexible():
        pattern = r'\{\s*"titre"\s*:\s*"([^"]*(?:\\.[^"]*)*)"\s*,\s*"description"\s*:\s*"((?:[^"\\]|\\\\.)*?)\s*"\s*\}'
        match = re.search(pattern, source_text, re.DOTALL | re.MULTILINE)
        if match:
            titre_raw = match.group(1)
            desc_raw = match.group(2)
            titre = (titre_raw.replace('\\"', '"').replace('\\n', ' ').replace('\n', ' ').replace('  ', ' ').strip())
            description = (desc_raw.replace('\\"', '"').replace('\\n', ' ').replace('\n', ' ').replace('  ', ' ').strip())
            if titre and description and len(titre) > 3 and len(description) > 10:
                return {
                    'titre': titre[:70],
                    'description': description[:150],
                    '_method': 'regex_flexible',
                    '_attempt': attempt
                }
        return None

    def _method_line_parsing():
        lines = source_text.split('\n')
        extracted_titre = None
        extracted_desc = []
        in_description = False
        import re as _re2
        for i, line in enumerate(lines):
            if '"titre"' in line and not extracted_titre:
                titre_match = _re2.search(r'"titre"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', line)
                if titre_match:
                    extracted_titre = titre_match.group(1)
            if '"description"' in line:
                in_description = True
                desc_match = _re2.search(r'"description"\s*:\s*"([^"]*)', line)
                if desc_match:
                    extracted_desc.append(desc_match.group(1))
                continue
            if in_description:
                if '}' in line: break
                s_strip = line.strip()
                if s_strip.startswith('"') and s_strip.endswith('"'):
                    content = s_strip[1:-1]
                    extracted_desc.append(content)
                elif s_strip:
                    extracted_desc.append(s_strip)
        if extracted_titre and extracted_desc:
            description = ' '.join(extracted_desc)
            return {
                'titre': extracted_titre.replace('\\"', '"').strip()[:70],
                'description': description.replace('\\"', '"').replace('\n', ' ').strip()[:150],
                '_method': 'line_parsing',
                '_attempt': attempt
            }
        return None

    def _method_raw_fallback():
        if not allow_raw_fallback: return None
        text_segments = []
        for line in source_text.split('\n'):
            line = line.strip()
            if len(line) < 3 or line in ["{", "}", "<<END>>", "<>"]:
                continue
            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            if len(line) > 5:
                text_segments.append(line)
        
        ok_strict, why = _is_likely_gemini_v15_2_strict(source_text)
        if ok_strict and len(text_segments) >= 2:
            titre = text_segments[0][:70]
            description = " ".join(text_segments[1:])[:150]
            return {
                'titre': titre,
                'description': description,
                '_method': 'raw_text_fallback',
                '_attempt': attempt,
                '_segments_used': len(text_segments)
            }
        return None

    # Liste ordonnée des méthodes (Nom, Fonction)
    methods = [
        ('regex_direct_v9_escaped', _method_regex_direct),
        ('regex_flexible', _method_regex_flexible),
        ('line_parsing', _method_line_parsing),
        ('raw_text_fallback', _method_raw_fallback)
    ]

    # --- INTELLIGENCE : Pattern Learning ---
    # Si une méthode a fonctionné précédemment (session courante OU cache), on la teste en premier
    if _LAST_SUCCESSFUL_METHOD_NAME:
        preferred_idx = next((i for i, (name, _) in enumerate(methods) if name == _LAST_SUCCESSFUL_METHOD_NAME), None)
        if preferred_idx is not None and preferred_idx > 0:
            preferred = methods.pop(preferred_idx)
            methods.insert(0, preferred) # Promotion en tête de liste

    # --- EXECUTION DYNAMIQUE ---
    for method_name, method_func in methods:
        try:
            result = method_func()
            if result:
                # Succès ! On mémorise la méthode pour la prochaine fois
                if _LAST_SUCCESSFUL_METHOD_NAME != method_name:
                    _LAST_SUCCESSFUL_METHOD_NAME = method_name
                    # Mise à jour du cache persistant
                    _save_successful_method_to_cache(method_name)
                    jlog('parse_v14_success_dynamic_new_pattern', method=method_name, attempt=attempt)
                else:
                    jlog('parse_v14_success_dynamic', method=method_name, attempt=attempt)
                return result
        except Exception as e:
             jlog(f'parse_v14_{method_name}_error', error=str(e)[:100], level='DEBUG')

    jlog('parse_v14_all_methods_failed', attempt=attempt, max_attempts=max_attempts, response_preview=source_text[:300])
    return None


# ===== PATCH #7: SAFE TIMEOUT SIGNALING =====
_TIMEOUT_MANAGER = None

def _get_timeout_manager():
    global _TIMEOUT_MANAGER
    if _TIMEOUT_MANAGER is not None:
        return _TIMEOUT_MANAGER
    try:
        from timeout_manager import CrossProcessTimeoutManager
        _TIMEOUT_MANAGER = CrossProcessTimeoutManager()
        jlog("be_timeout_manager_initialized", level="DEBUG")
        return _TIMEOUT_MANAGER
    except ImportError as e:
        jlog("be_timeout_manager_import_error", error=str(e), level="WARN")
        return None
    except Exception as e:
        jlog("be_timeout_manager_init_error", error=str(e), error_type=type(e).__name__, level="ERROR")
        return None

def _safe_signal_activity(is_progress: bool = False, extension_s: float = 30.0):
    try:
        manager = _get_timeout_manager()
        if manager is None:
            jlog("be_signal_activity_manager_unavailable", is_progress=is_progress, level="DEBUG")
            return False
        
        new_timeout = manager.signal_worker_activity(
            is_progress=is_progress,
            extension_s=extension_s,
            reason="be_producer_signal"
        )
        
        jlog("be_signal_activity_success", is_progress=is_progress, extension_s=extension_s, new_heartbeat=round(new_timeout, 1), level="DEBUG")
        return True
    
    except AttributeError as attr_err:
        try:
            manager = _get_timeout_manager()
            if manager and hasattr(manager, 'extend_on_activity'):
                manager.extend_on_activity(extension_s)
                jlog("be_signal_activity_fallback_old_api", error="new_api_missing, using old", level="WARN")
                return True
        except Exception:
            pass
        jlog("be_signal_activity_attribute_error", error=str(attr_err)[:100], level="WARN")
        return False
    
    except Exception as e:
        jlog("be_signal_activity_error", error=str(e)[:100], error_type=type(e).__name__, level="ERROR")
        return False


_BEX_URL_PAT = re.compile(r"/_(/)?BardChatUi/data/batchexecute", re.I)
_BL_VERSION_PAT = re.compile(r"[?&]bl=([^&]+)")


class BEProducer:
    """BE producer acting only as fallback source."""
    def __init__(self, page: Page, on_progress: Callable[[str], None], on_done: Callable[[str, Optional[str]], None]) -> None:
        self.page = page
        self.on_progress_cb = on_progress
        self.on_done_cb = on_done
        self.seen: bool = False
        self.done: bool = False
        self._resp_handler = self._on_response
        self._start_ts: Optional[float] = None
        
        self._agg: Dict[str, Dict[str, Any]] = {}  # {rpcid: {"t": ts, "buf": str}}
        self._agg_window_s = 12.0

    def _agg_push(self, rpc_meta: dict, cand: str) -> str:
        """Agrége les fragments de texte par RPCID sur une fenêtre de temps."""
        now = time.monotonic()
        
        for rpcid in (rpc_meta or {}).keys():
            buf = self._agg.get(rpcid, {"t": now, "buf": ""})
            if cand:
                sep = " " if buf["buf"] and not buf["buf"].endswith((" ", "\n")) else ""
                buf["buf"] = (buf["buf"] + sep + cand).strip()
            buf["t"] = now
            self._agg[rpcid] = buf
            
        to_del = [k for k,v in self._agg.items() if now - v["t"] > self._agg_window_s]
        for k in to_del: self._agg.pop(k, None)
        
        best = max((v["buf"] for v in self._agg.values()), key=lambda s: len(s or ""), default="")
        return best

    async def start(self) -> None:
        if self.page.is_closed(): jlog("be_start_fail_page_closed"); return
        try: 
            self.page.on("response", self._resp_handler)
            self._start_ts = time.monotonic()
            jlog("be_start_ok")
        except Exception as e: jlog("be_start_error", error=str(e), error_type=type(e).__name__)

    async def stop(self) -> None:
        try:
            if not self.page.is_closed():
                 if hasattr(self.page, "remove_listener"): self.page.remove_listener("response", self._resp_handler)
                 elif hasattr(self.page, "off"): self.page.off("response", self._resp_handler)
            jlog("be_stop_ok")
        except Exception as e: jlog("be_stop_remove_listener_error", error=str(e), level="WARN")
        finally:
             self._mt = None
             self.seen = False

    async def _on_response(self, resp: Response) -> None:
        bl_version = "unknown"; rpcids_seen = []; url = "unknown"
        try:
            url = resp.url or ""
            if not _BEX_URL_PAT.search(url): return
            self.seen = True

            try:
                bl_match = _BL_VERSION_PAT.search(url); bl_version = bl_match.group(1) if bl_match else "unknown"
                parsed_url = urlparse(url); query_params = parse_qs(parsed_url.query); rpcids_seen = query_params.get('rpcids', [])
            except Exception as url_parse_err: jlog("be_url_parse_warn", url=url, error=str(url_parse_err))

            status = resp.status
            if not (200 <= status < 300): jlog("be_skip_non_2xx", url=url, status=status); return

            try: body = await asyncio.wait_for(resp.text(), timeout=15.0)
            except asyncio.TimeoutError: jlog("be_resp_text_timeout", url=url); return
            except Exception as e: jlog("be_resp_text_error", url=url, error=str(e)); return
            if not body: jlog("be_skip_empty_body", url=url, status=status); return
            
            
            body_len = len(body)
            low = body.lower()
            accept = False
            now = time.monotonic()
            start_ts = self._start_ts or now
            
            # Décodage batchexecute
            cand, meta = _try_decode_batchexecute_to_text(body)
            jlog("be_bex_precheck_decode", url=url, segments=meta.get("segments",0), strings=meta.get("strings",0), cand_len=len(cand))
            
            # Agrégation
            if meta.get("rpcids"):
                cand = self._agg_push(meta.get("rpcids"), cand)
                jlog("be_bex_agg_push_complete", rpcids=list(meta.get("rpcids").keys())[:5], new_cand_len=len(cand))
            
            if len(cand) >= 10:
                accept = True
                body_for_parser = cand
            else:
                body_for_parser = body
            
            # Tolérance initiale
            if not accept and (now - start_ts) < 5.0:
                if "json" in resp.headers.get("content-type","") and body_len >= 100:
                    accept = True
                    jlog("be_accept_tolerance_window", len=body_len)

            # Heuristique positive
            NEGATIVE_SIGNS_HEURISTIC = ["wrb.fr", "ESY5D", "f.req", "XSRF_TOKEN"]
            if not accept and body_len >= 120 and not any(neg in low for neg in NEGATIVE_SIGNS_HEURISTIC):
                if (re.search(r'[a-zA-Z]{3,}\s+[a-zA-Z]{3,}', body) and ('"' in body or '.' in body)) or \
                   ('"titre"' in low or '"description"' in low):
                     accept = True
                     jlog("be_accept_positive_heuristic", len=body_len)

            if not accept:
                jlog("be_drop_noise_body", url=url, status=status, len=body_len, cand_len=len(cand)); return

            # Parsing V14
            parsed_data = None
            for parse_attempt in range(1, 4):
                try:
                    parsed_data = await parse_gemini_response_intelligent_v14(
                        raw_response=body_for_parser,
                        attempt=parse_attempt,
                        max_attempts=3,
                        debug=True,
                        validate_gemini_signatures=True,
                        allow_raw_fallback=False
                    )
                    
                    if parsed_data:
                        jlog('parse_success_attempt',
                             attempt=parse_attempt,
                             method=parsed_data.get('_method', 'unknown'),
                             titre_len=len(parsed_data.get('titre', '')),
                             desc_len=len(parsed_data.get('description', '')))
                        break
                    else:
                        if parse_attempt < 3:
                            jlog('parse_retry_next_method', attempt=parse_attempt)
                            await asyncio.sleep(0.2 * parse_attempt)
                
                except Exception as parse_exc:
                    jlog('parse_exception', attempt=parse_attempt, error=str(parse_exc)[:100], level='WARN')
                    continue

            if parsed_data:
                try:
                    _safe_signal_activity(is_progress=True, extension_s=60.0)
                except Exception as signal_err:
                    jlog("be_signal_hard_progress_error", error=str(signal_err)[:100], level="WARN")
                
                try:
                    json_string_payload = json.dumps(parsed_data, ensure_ascii=False)
                    self.on_progress_cb(json_string_payload)
                except Exception as cb_err:
                    jlog("be_on_progress_callback_error", error=str(cb_err))
            else:
                jlog('parse_final_failure', response_preview=body_for_parser[:200], level='ERROR')
                try:
                    _safe_signal_activity(is_progress=False, extension_s=30.0)
                except Exception as signal_err:
                    jlog("be_signal_soft_activity_error", error=str(signal_err)[:100], level="WARN")

        except Exception as e:
             if not self.page.is_closed():
                  jlog("be_on_response_unexpected_error", url=url, error=type(e).__name__, message=str(e))