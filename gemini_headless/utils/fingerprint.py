# -*- coding: utf-8 -*-
import json
import random
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, asdict

# ============================================================================
# PARTIE 1 : EMPREINTE NAVIGATEUR (Browser Fingerprint)
# ============================================================================

UAS: List[str] = [
    # Chrome 123–128 Windows 10/11 — éventail plausible
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

COMMON_SCREENS: List[Tuple[int, int]] = [(1920,1080), (1366,768), (1536,864), (2560,1440)]
COMMON_TZS: List[str] = ["Europe/Paris","Europe/Madrid","Europe/Berlin","Europe/Rome"]

@dataclass
class Fingerprint:
    user_agent: str
    webgl_vendor: str = "Google Inc. (Intel)"
    renderer: str = "ANGLE (Intel, Intel(R) UHD Graphics 630, D3D11)"
    platform: str = "Win32"
    screen: Tuple[int, int] = (1920,1080)
    timezone: str = "Europe/Paris"
    fonts: List[str] = None  # type: ignore

    @staticmethod
    def load_or_seed(profile, policy: str = "stable"):
        """
        Charge un fingerprint stable si présent, sinon en génère un et l'écrit.
        """
        # Support pour objet profile ou chemin direct
        base_dir = profile.dir if hasattr(profile, 'dir') else Path(str(profile))
        path = base_dir / "fingerprint.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and policy == "stable":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Filtrage pour éviter les erreurs d'init si le JSON est vieux
                valid_keys = Fingerprint.__annotations__.keys()
                filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                return Fingerprint(**filtered_data)
            except Exception:
                pass # Fallback si fichier corrompu

        ua = random.choice(UAS)
        screen = random.choice(COMMON_SCREENS)
        tz = random.choice(COMMON_TZS)
        fonts = ["Segoe UI", "Arial", "Times New Roman", "Calibri", "Monaco"]
        fp = Fingerprint(user_agent=ua, screen=screen, timezone=tz, fonts=fonts)
        path.write_text(json.dumps(asdict(fp), ensure_ascii=False, indent=2), encoding="utf-8")
        return fp

def build_launch_args(fp: Fingerprint, proxy: Optional[Dict[str, str]] = None, timezone: Optional[str] = None):
    """
    Arguments Chromium furtifs et cohérents avec le fingerprint.
    """
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=Translate,IsolateOrigins,site-per-process",
        "--no-first-run",
        "--password-store=basic",
        "--lang=fr-FR",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-dev-shm-usage",
    ]
    if timezone or fp.timezone:
        args += [f"--force-timezone={timezone or fp.timezone}"]
    if proxy and "server" in proxy:
        args += [f'--proxy-server={proxy["server"]}']
    # cohérence écran
    w, h = fp.screen
    args += [f"--window-size={w},{h}"]
    return args


# ============================================================================
# PARTIE 2 : INTELLIGENCE EVOLUTIVE DU DOM (DOM Signature Learning)
# ============================================================================

class DOMSignatureLearner:
    """
    Opportunité N°2 : Apprend les sélecteurs qui fonctionnent pour s'adapter
    aux changements d'interface de Google sans mise à jour du code.
    """
    def __init__(self, profile_dir: Path):
        self.storage_path = profile_dir / "learned_dom_signatures.json"
        self.signatures = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.storage_path.exists():
            try:
                return json.loads(self.storage_path.read_text(encoding="utf-8"))
            except:
                return {}
        return {}

    def save(self):
        try:
            self.storage_path.write_text(json.dumps(self.signatures, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_best_selector(self, intent: str, default: str) -> str:
        """Retourne le meilleur sélecteur appris pour une intention donnée (ex: 'input_field')."""
        learned = self.signatures.get(intent)
        if learned and learned.get("success_count", 0) > 2:
            # On utilise le learned si confirmé plusieurs fois
            return learned["selector"]
        return default

    def learn_success(self, intent: str, selector: str, context_html_hash: str = None):
        """Enregistre un succès pour un sélecteur donné."""
        if intent not in self.signatures:
            self.signatures[intent] = {"selector": selector, "success_count": 1, "last_updated": time.time()}
        else:
            if self.signatures[intent]["selector"] == selector:
                self.signatures[intent]["success_count"] += 1
                self.signatures[intent]["last_updated"] = time.time()
            else:
                # Nouveau concurrent : on remplace si l'ancien est vieux (> 7 jours)
                if time.time() - self.signatures[intent]["last_updated"] > 604800:
                    self.signatures[intent] = {"selector": selector, "success_count": 1, "last_updated": time.time()}
        self.save()

    def mark_failure(self, intent: str):
        """Décrémente la confiance en cas d'échec."""
        if intent in self.signatures:
            self.signatures[intent]["success_count"] = max(0, self.signatures[intent]["success_count"] - 1)
            self.save()