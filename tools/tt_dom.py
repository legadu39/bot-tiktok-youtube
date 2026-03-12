### bot tiktok youtube/tools/tt_dom.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TikTok Uploader — Fonctions d'interaction DOM (CRITICAL MODE ++ / Remediated v5).

FIXES v5:
  - NEUTRAL_BASENAME est maintenant session-scoped (généré à la demande, plus de singleton global).
  - CURRENT_LATENCY_FACTOR encapsulé dans LatencyContext (thread-safe, plus de global mutable).
  - el.proto corrigé en el.__proto__ dans _native_setter_js.
  - Cleanup automatique des fichiers .tt_tmp après usage.
  - validate_redirect_to_description_page : correction du faux positif URL upload initial.
  - find_and_click_next_button utilise runner.eval() (public) et non runner._eval() (privé).
  - Toutes les fonctions acceptent un LatencyContext explicite.
"""

import json
import re
import time
import random
import os
import shutil
import threading
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Tuple

from tt_cdp import CdpClient
from tt_utils import jlog

if TYPE_CHECKING:
    from tt_runner import UploadRunner

from tt_constants import TT_TMP_DIRNAME


# ---------------------------------------------------------------------------
# LATENCY CONTEXT — Remplace le global mutable CURRENT_LATENCY_FACTOR
# ---------------------------------------------------------------------------

class LatencyContext:
    """
    Contexte de latence thread-safe.
    Chaque session d'upload dispose de son propre contexte, évitant toute
    pollution entre sessions concurrentes ou séquentielles.
    """
    def __init__(self, initial_factor: float = 1.0):
        self._lock = threading.Lock()
        self._factor = initial_factor

    @property
    def factor(self) -> float:
        with self._lock:
            return self._factor

    @factor.setter
    def factor(self, value: float):
        with self._lock:
            self._factor = max(1.0, min(5.0, float(value)))

    def scale(self, base: float) -> float:
        return base * self.factor

    def update_from_duration(self, duration: float, expected_fast_time: float = 1.0):
        if duration > expected_fast_time:
            new_factor = duration / expected_fast_time
            self.factor = new_factor
            jlog("network_aware",
                 msg=f"Ralentissement détecté ({duration:.2f}s). Latency Factor → {self.factor:.2f}x")
        else:
            self.factor = 1.0
            jlog("network_aware", msg="Système réactif. Latency Factor = 1.0x")


# Instance par défaut (utilisée si aucun contexte explicite n'est fourni — rétrocompatibilité)
_default_latency = LatencyContext()


# ---------------------------------------------------------------------------
# SESSION FILE NAMER — Remplace le singleton NEUTRAL_BASENAME
# ---------------------------------------------------------------------------

def make_session_basename() -> str:
    """
    Génère un basename aléatoire unique PER APPEL.
    Contrairement à l'ancienne implémentation (singleton module-level),
    deux uploads simultanés dans le même processus obtiennent des noms différents.
    """
    return f"nf_{random.randrange(16**8):08x}"


# ---------------------------------------------------------------------------
# DOM DARWIN CACHE
# ---------------------------------------------------------------------------

class DomDarwinCache:
    """
    Mémoire persistante pour les sélecteurs CSS gagnants.
    Expiration automatique après 7 jours.
    Thread-safe via RLock.
    """
    CACHE_FILE = Path("dom_darwin_cache.json")
    EXPIRY_SECONDS = 7 * 86400
    _lock = threading.RLock()

    @classmethod
    def load(cls) -> dict:
        with cls._lock:
            if not cls.CACHE_FILE.exists():
                return {}
            try:
                with open(cls.CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() - data.get("timestamp", 0) > cls.EXPIRY_SECONDS:
                    return {}
                return data.get("selectors", {})
            except Exception:
                return {}

    @classmethod
    def save_winner(cls, key: str, selector: str):
        if not selector:
            return
        with cls._lock:
            try:
                current = cls.load()
                current[key] = selector
                with open(cls.CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"timestamp": time.time(), "selectors": current}, f, indent=2)
            except Exception:
                pass

    @classmethod
    def get_winner(cls, key: str) -> Optional[str]:
        return cls.load().get(key)


# ---------------------------------------------------------------------------
# GESTION SYSTÈME DE FICHIERS — Neutralisation + Cleanup
# ---------------------------------------------------------------------------

def _make_neutral_upload_copy(src_path: Path, session_basename: Optional[str] = None) -> Tuple[str, Path]:
    """
    Crée une copie temporaire avec un nom aléatoire pour éviter le fingerprinting.

    Returns:
        Tuple (chemin_str_copie, tmp_dir_path) — tmp_dir_path est retourné pour
        permettre le cleanup ultérieur par l'appelant.

    FIX v5:
        - session_basename est passé explicitement (plus de singleton global).
        - Retourne le répertoire tmp pour que l'appelant puisse nettoyer.
    """
    p = Path(src_path)
    tmp_dir = p.parent / TT_TMP_DIRNAME
    tmp_dir.mkdir(exist_ok=True)

    basename = session_basename or make_session_basename()
    dst = tmp_dir / f"{basename}{p.suffix.lower()}"

    try:
        shutil.copy2(p, dst)
        return str(dst), tmp_dir
    except Exception as e:
        jlog("neutral_copy_failed", stage="init", error=str(e))
        return str(p), tmp_dir


def cleanup_neutral_copy(tmp_dir: Optional[Path], session_basename: Optional[str]):
    """
    Supprime le fichier temporaire créé par _make_neutral_upload_copy.
    Appeler après la fin de l'upload (succès ou échec).
    """
    if not tmp_dir or not session_basename:
        return
    try:
        for f in tmp_dir.glob(f"{session_basename}.*"):
            f.unlink(missing_ok=True)
        # Supprime le répertoire tmp s'il est vide
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
    except Exception as e:
        jlog("neutral_copy_cleanup_failed", error=str(e))


# ---------------------------------------------------------------------------
# CONSTANTES JS — INTELLIGENCE HEURISTIQUE
# ---------------------------------------------------------------------------

JS_FUZZY_CAPTION_SCAN = r"""
(function() {
    const candidates = document.querySelectorAll('div[contenteditable="true"], textarea, input[type="text"]');
    let bestEl = null;
    let maxScore = 0;
    let bestSelector = "";

    function generateSelector(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        if (el.dataset.e2e) return `[data-e2e="${el.dataset.e2e}"]`;
        if (el.className) {
            const classes = el.className.split(' ').filter(c => c.length > 4 && !/\d/.test(c));
            if (classes.length > 0) return '.' + CSS.escape(classes[0]);
        }
        return el.tagName.toLowerCase();
    }

    candidates.forEach(el => {
        let score = 0;
        const html = el.outerHTML.toLowerCase();
        const placeholder = (el.getAttribute('placeholder') || "").toLowerCase();
        const dataE2E = (el.getAttribute('data-e2e') || "").toLowerCase();
        const ariaLabel = (el.getAttribute('aria-label') || "").toLowerCase();

        if (dataE2E.includes('caption') || dataE2E.includes('description')) score += 50;
        if (ariaLabel.includes('caption') || ariaLabel.includes('description') || ariaLabel.includes('légende')) score += 40;
        if (html.includes('mention') || html.includes('hashtag')) score += 20;
        if (placeholder.includes('tell us') || placeholder.includes('dites-nous') || placeholder.includes('describe')) score += 30;
        if (el.tagName === 'DIV' && el.getAttribute('contenteditable') === 'true') score += 15;

        if (placeholder.includes('title') || placeholder.includes('titre')) score -= 50;
        if (dataE2E.includes('search')) score -= 100;
        if (el.getAttribute('type') === 'search') score -= 100;

        if (score > maxScore) {
            maxScore = score;
            bestEl = el;
            try { bestSelector = generateSelector(el); } catch(_) { bestSelector = el.tagName.toLowerCase(); }
        }
    });

    if (bestEl && maxScore > 20) {
        bestEl.setAttribute('data-nexus-target', 'true');
        return { found: true, score: maxScore, tag: bestEl.tagName, selector: bestSelector || '[data-nexus-target="true"]' };
    }
    return { found: false, best_score: maxScore };
})();
"""


# ---------------------------------------------------------------------------
# G3 ROBUST UTILITIES
# ---------------------------------------------------------------------------

FILENAME_PREFILL_RE = re.compile(
    r"^\s*(?:\d{8}T\d{6}[_\w-]|nf_[0-9a-f]{8}|video|vid[eé]o|clip|movie)\s*",
    re.IGNORECASE
)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u200b", "")).strip()


def _reads_caption_js(selector_json: str) -> str:
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, text:''}};
    const txt = (el.value!==undefined?el.value:(el.innerText||el.textContent||''));
    return {{ok:true, text: txt}};
    }})()
    """


def _select_all_js(selector_json: str) -> str:
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, why:'not_found'}};
    el.focus();
    try {{
        if (typeof el.select === 'function') {{ el.select(); return {{ok:true, via:'select()'}}; }}
        const rng = document.createRange();
        rng.selectNodeContents(el);
        const sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(rng);
        return {{ok:true, via:'range'}};
    }} catch(e) {{
        try {{ document.execCommand('selectAll', false, null); return {{ok:true, via:'execCommand'}}; }}
        catch(_e) {{ return {{ok:false, why:'select_failed'}}; }}
    }}
    }})()
    """


def guard_mutation_js(selector_json: str, desired_json: str, ms: int = 1500) -> str:
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, why:'not_found'}};
    try {{ if(window.__ttCaptionGuard) window.__ttCaptionGuard.disconnect(); }} catch(e){{}}
    const desired = {desired_json};
    const ob = new MutationObserver(function(_m){{
        const txt = (el.value!==undefined?el.value:(el.innerText||el.textContent||''));
        if (txt.trim() !== desired.trim()) {{
            try {{
                const rng = document.createRange();
                rng.selectNodeContents(el);
                const sel = window.getSelection();
                sel.removeAllRanges(); sel.addRange(rng);
                document.execCommand('insertText', false, desired);
            }} catch(_e) {{}}
        }}
    }});
    window.__ttCaptionGuard = ob;
    ob.observe(el, {{subtree:true, childList:true, characterData:true}});
    setTimeout(()=>{{ try{{ob.disconnect();}}catch(_e){{}} }}, {ms});
    return {{ok:true}};
    }})()
    """


def _dom_insert_text_js(selector_json: str, desired_json: str) -> str:
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, why:'not_found'}};
    el.focus();
    try {{
        document.execCommand('insertText', false, {desired_json});
        return {{ok:true}};
    }} catch(e) {{
        return {{ok:false, why:'exec_failed:'+String(e)}};
    }}
    }})();
    """


def _native_setter_js(selector_json: str, desired_json: str) -> str:
    """
    FIX v5: el.proto → el.__proto__ (était un bug silencieux accédant
    à une propriété inexistante au lieu du prototype réel de l'élément).
    """
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, why:'not_found'}};
    try {{
        el.focus();
        if (el.value !== undefined) {{
            const desc = Object.getOwnPropertyDescriptor(el.__proto__, 'value')
                || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
                || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
            if (desc && desc.set) {{
                desc.set.call(el, {desired_json});
            }} else {{
                el.value = {desired_json};
            }}
        }} else {{
            el.textContent = {desired_json};
        }}
        el.dispatchEvent(new Event('input', {{bubbles:true, cancelable:true}}));
        el.dispatchEvent(new Event('change', {{bubbles:true, cancelable:true}}));
        return {{ok:true}};
    }} catch(e) {{
        return {{ok:false, why:'setter_failed:'+String(e)}};
    }}
    }})();
    """


# ---------------------------------------------------------------------------
# INTELLIGENCE N°2 — RÉSOLUTION DYNAMIQUE DU SÉLECTEUR
# ---------------------------------------------------------------------------

def resolve_caption_selector_smart(runner: 'UploadRunner') -> str:
    """
    Résolution en 3 niveaux : Cache Darwinien → Fuzzy Scan → Fallback statique.
    FIX v5 : utilise runner.eval() (public) au lieu de runner._eval() (privé).
    """
    cached = DomDarwinCache.get_winner("caption_input")
    if cached:
        check_js = f"!!document.querySelector({json.dumps(cached)})"
        try:
            if runner.eval(check_js, True, 1.5):
                jlog("dom_resolution", strategy="cache_hit", selector=cached)
                return cached
        except Exception:
            pass

    jlog("dom_resolution", strategy="fuzzy_scan_start")
    try:
        res = runner.eval(JS_FUZZY_CAPTION_SCAN, True, 2.5) or {}
    except Exception as e:
        jlog("dom_resolution", strategy="fuzzy_scan_error", error=str(e))
        res = {}

    if res.get("found") and res.get("selector"):
        winner = res["selector"]
        jlog("dom_resolution", strategy="fuzzy_success", score=res.get("score"), selector=winner)
        DomDarwinCache.save_winner("caption_input", winner)
        return winner

    fallback = '[data-e2e*="caption"] div[contenteditable="true"]'
    jlog("dom_resolution", strategy="fallback_static", selector=fallback)
    return fallback


# ---------------------------------------------------------------------------
# set_description_robust
# ---------------------------------------------------------------------------

def set_description_robust(
    runner: 'UploadRunner',
    desc_selector_used: str,
    description: str,
    max_attempts: int = 6,
    base_sleep: float = 0.18,
    stable_reads: int = 4,
    stable_interval_s: float = 0.28,
    guard_ms: int = 2500,
    latency: Optional[LatencyContext] = None,
) -> bool:
    """
    Définit la description avec une stratégie en couches.
    FIX v5 :
      - Accepte un LatencyContext explicite (plus de global mutable).
      - Utilise runner.eval() (public).
      - Résolution auto du sélecteur si 'auto' ou absent.
    """
    lx = latency or _default_latency

    base_sleep = lx.scale(base_sleep)
    stable_interval_s = lx.scale(stable_interval_s)

    if not desc_selector_used or desc_selector_used == "auto":
        desc_selector_used = resolve_caption_selector_smart(runner)

    sel_j = json.dumps(desc_selector_used)
    desired_j = json.dumps(description)

    try:
        runner.eval(guard_mutation_js(sel_j, desired_j, guard_ms), True, lx.scale(2.0))
    except Exception as e:
        jlog("g3_mutation_guard_failed", stage="g3", error=str(e))

    def _read_norm() -> str:
        try:
            got = runner.eval(_reads_caption_js(sel_j), True, lx.scale(2.0)) or {}
            raw = (got.get("text") if isinstance(got, dict) else "") or ""
            return _normalize(raw)
        except Exception as e:
            jlog("g3_readback_failed", stage="g3", error=str(e))
            return ""

    want = _normalize(description)

    for i in range(max_attempts):
        # Étape 1 : Sélection totale
        try:
            runner.eval(_select_all_js(sel_j), True, lx.scale(2.0))
        except Exception as e:
            jlog("g3_select_all_failed", stage="g3", attempt=i, error=str(e))

        time.sleep(lx.scale(0.08))

        # Étape 2 : Injection via CDP Input.insertText
        cdp_ok = False
        try:
            runner.cd.send("Input.insertText", {"text": description}, timeout=lx.scale(10.0))
            cdp_ok = True
        except Exception as e:
            jlog("g3_insertText_cdp_failed", stage="g3", attempt=i, error=str(e))

        # Étape 3 : Fallback DOM execCommand
        if not cdp_ok:
            try:
                runner.eval(_dom_insert_text_js(sel_j, desired_j), True, lx.scale(2.0))
            except Exception as e:
                jlog("g3_insertText_dom_failed", stage="g3", attempt=i, error=str(e))

        # Étape 4 : Native setter si le texte est toujours incorrect
        txt = _read_norm()
        if txt != want or FILENAME_PREFILL_RE.match(txt or ""):
            try:
                runner.eval(_native_setter_js(sel_j, desired_j), True, lx.scale(2.0))
            except Exception as e:
                jlog("g3_insertText_setter_failed", stage="g3", attempt=i, error=str(e))

        # Étape 5 : Vérification de stabilité (N lectures consécutives correctes)
        ok_reads = 0
        for _ in range(stable_reads):
            time.sleep(stable_interval_s)
            txt = _read_norm()
            if txt == want and not FILENAME_PREFILL_RE.match(txt or ""):
                ok_reads += 1
            else:
                jlog("g3_stability_check_fail", stage="g3", attempt=i, read=txt, want=want)
                break

        if ok_reads == stable_reads:
            try:
                runner.eval(
                    f"(function(){{const el=document.querySelector({sel_j}); if(el) el.blur(); }})()",
                    True, 1.0
                )
            except Exception:
                pass
            jlog("g3_set_desc_validate_ok", stage="g3", attempt=i, read_len=len(txt))
            return True

        # Ctrl+A CDP pour le prochain tour
        try:
            for ktype in ("keyDown", "keyUp"):
                runner.cd.send("Input.dispatchKeyEvent", {
                    "type": ktype, "modifiers": 2, "key": "a",
                    "code": "KeyA", "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65
                })
        except Exception:
            pass

        time.sleep(base_sleep * (1 + i / 3.0))

    return False


# ---------------------------------------------------------------------------
# revalidate_caption_before_post
# ---------------------------------------------------------------------------

def revalidate_caption_before_post(
    runner: 'UploadRunner',
    desc_selector_used: str,
    description: str,
    latency: Optional[LatencyContext] = None,
) -> bool:
    """
    Vérification finale pré-publication.
    FIX v5 : utilise runner.eval() (public), latency explicite.
    """
    lx = latency or _default_latency

    if not desc_selector_used or desc_selector_used == "auto":
        desc_selector_used = resolve_caption_selector_smart(runner)

    sel_j = json.dumps(desc_selector_used)
    want = _normalize(description)

    def stable_ok() -> bool:
        ok = 0
        for _ in range(4):
            time.sleep(lx.scale(0.28))
            try:
                got = runner.eval(_reads_caption_js(sel_j), True, lx.scale(2.0)) or {}
                txt = _normalize((got.get("text") if isinstance(got, dict) else "") or "")
            except Exception:
                txt = ""
            if txt == want and not FILENAME_PREFILL_RE.match(txt or ""):
                ok += 1
            else:
                jlog("g5_reval_stability_fail", stage="g5", read=txt, want=want)
                break
        return ok == 4

    if stable_ok():
        jlog("g5_revalidation_ok", stage="g5", action="pre_post_check_ok")
        return True

    jlog("g5_revalidation_mismatch", stage="g5", action="pre_post_correction_start")
    if set_description_robust(runner, desc_selector_used, description,
                               max_attempts=3, guard_ms=2000, latency=lx):
        if stable_ok():
            jlog("g5_revalidation_correction_ok", stage="g5", action="pre_post_correction_success")
            return True

    jlog("g5_revalidation_failed_blocking", stage="g5", action="abort_post")
    return False


# ---------------------------------------------------------------------------
# Fonctions de validation (G2.5)
# ---------------------------------------------------------------------------

def capture_page_state_hash() -> str:
    """Retourne le JS (string) à évaluer pour obtenir un snapshot de l'état de la page."""
    return r"""
    (function() {
        const state = {
            url: window.location.href,
            url_params: new URLSearchParams(window.location.search).toString(),
            has_title_input: !!document.querySelector('input[type="text"]'),
            has_contenteditable: !!document.querySelector('[contenteditable="true"]'),
            has_textarea: !!document.querySelector('textarea'),
            inputs_count: document.querySelectorAll('input[type="text"]').length,
            editables_count: document.querySelectorAll('[contenteditable="true"]').length,
            textareas_count: document.querySelectorAll('textarea').length,
            progress_bar: !!document.querySelector('progress, [role="progressbar"]'),
            next_button_visible: !![...document.querySelectorAll('button')].find(b =>
                /next|continue|suivant|continuer|proceed/i.test((b.innerText || b.textContent || ''))
            ),
            title: document.title.substring(0, 100),
        };

        const stateStr = JSON.stringify(state);
        let hash = 0;
        for (let i = 0; i < stateStr.length; i++) {
            const char = stateStr.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }

        return {
            ...state,
            hash: Math.abs(hash).toString(16),
            timestamp: Date.now()
        };
    })();
    """


def find_and_click_next_button(
    runner: 'UploadRunner',
    max_retries: int = 3,
    timeout_between_retries: float = 2.0,
    latency: Optional[LatencyContext] = None,
) -> bool:
    """
    Trouve et clique sur le bouton "Suivant/Next".
    FIX v5 :
      - Utilise runner.eval() (public) exclusivement.
      - Accepte un LatencyContext explicite.
    """
    lx = latency or _default_latency

    jlog("g2_5_next_button_search", stage="g2_5_ultra", action="start")

    try:
        pre_state = runner.eval(capture_page_state_hash(), True, lx.scale(5.0)) or {}
        current_url = pre_state.get('url', '')
        is_on_upload_route = ("/upload" in current_url) or ("tiktokstudio/upload" in current_url)
        if not is_on_upload_route:
            jlog("g2_5_precondition_failed", stage="g2_5_ultra",
                 decision_reason="Wrong URL context", url=current_url)
            return False
    except Exception as e:
        jlog("g2_5_precondition_exception", stage="g2_5_ultra", error=str(e))
        return False

    find_next_script = r"""
    (() => {
        function vis(el) {
            if (!el) return false;
            const s = getComputedStyle(el);
            return s.display !== 'none' && s.visibility !== 'hidden' &&
                   el.offsetParent !== null && el.offsetHeight > 10 && el.offsetWidth > 10;
        }

        let candidates = [...document.querySelectorAll('button')].filter(b =>
            vis(b) && /next|continue|suivant|continuer|proceed/i.test((b.innerText || b.textContent || ''))
        );

        if (candidates.length > 0) {
            return { found: true, strategy: 'text_match', label: (candidates[0].innerText || '').trim() };
        }

        candidates = [...document.querySelectorAll(
            'button[data-testid*="next" i], button[aria-label*="next" i]'
        )].filter(vis);
        if (candidates.length > 0) {
            return { found: true, strategy: 'data_testid_next',
                     label: candidates[0].getAttribute('data-testid') || '' };
        }

        return { found: false };
    })();
    """

    click_script = r"""
    (async () => {
        function vis(el) {
            if (!el) return false;
            const s = getComputedStyle(el);
            return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetParent !== null;
        }

        let button = [...document.querySelectorAll('button')].find(b =>
            vis(b) && /next|continue|suivant|continuer|proceed/i.test((b.innerText || b.textContent || ''))
        );

        if (!button) {
            button = [...document.querySelectorAll(
                'button[data-testid*="next" i], button[aria-label*="next" i]'
            )].find(vis);
        }

        if (!button) return { clicked: false };

        button.scrollIntoView({ behavior: 'smooth', block: 'center' });
        await new Promise(r => setTimeout(r, 500));
        button.click();
        return { clicked: true, label: (button.innerText || '').trim() };
    })();
    """

    for attempt in range(max_retries):
        try:
            discovery = runner.eval(find_next_script, True, lx.scale(5.0)) or {}
            if not discovery.get('found'):
                if attempt < max_retries - 1:
                    time.sleep(timeout_between_retries * lx.factor)
                continue

            jlog("g2_5_next_button_detected", stage="g2_5_ultra", ui_state=discovery)

            click_result = runner.eval(click_script, True, lx.scale(10.0)) or {}
            if click_result.get('clicked'):
                jlog("g2_5_next_button_clicked", stage="g2_5_ultra",
                     label=click_result.get('label', ''))
                time.sleep(lx.scale(2.0))
                return True

        except Exception as e:
            jlog("g2_5_next_button_exception", stage="g2_5_ultra", attempt=attempt, error=str(e))
            if attempt < max_retries - 1:
                time.sleep(timeout_between_retries * lx.factor)

    return False


def validate_redirect_to_description_page(
    runner: 'UploadRunner',
    expected_params: Optional[list] = None,
    timeout_s: float = 20.0,
    latency: Optional[LatencyContext] = None,
) -> dict:
    """
    Valide que la page de description est bien chargée après l'upload.

    FIX v5 :
      - Correction du faux positif URL : "/tiktokstudio/upload" SANS "step=" est la page
        d'UPLOAD INITIALE, pas la page de description. On exige désormais au minimum la
        présence des champs éditables ET du bouton Post pour valider, indépendamment de l'URL.
      - Utilise runner.eval() (public).
      - Accepte LatencyContext.
    """
    if expected_params is None:
        expected_params = ['step=description', 'step=edit', 'step=details']

    lx = latency or _default_latency
    adjusted_timeout = lx.scale(timeout_s)

    jlog("g2_5_redirect_validation_start", stage="g2_5_ultra", timeout_adjusted=adjusted_timeout)

    t0 = time.monotonic()

    while (time.monotonic() - t0) < adjusted_timeout:
        try:
            state = runner.eval(capture_page_state_hash(), True, lx.scale(5.0)) or {}
            current_url = state.get('url', '')

            # FIX : on n'accepte plus "/tiktokstudio/upload" sans "step=" comme valide.
            # La page description a soit un paramètre step= connu, soit suffisamment
            # d'éléments DOM caractéristiques (champs + bouton Post).
            url_has_known_step = any(param in current_url for param in expected_params)

            has_editable = state.get('has_contenteditable') or state.get('has_textarea')
            has_input = state.get('has_title_input')

            # Le bouton "Post/Publier" est le signal le plus fiable qu'on est sur la bonne page
            has_post_button = False
            try:
                has_post_button = runner.eval(r"""
                (() => {
                    const btns = [...document.querySelectorAll('button')];
                    return !!btns.find(b =>
                        /^(post|publier)$/i.test((b.innerText || b.textContent || '').trim())
                    );
                })()
                """, True, lx.scale(5.0)) or False
            except Exception:
                pass

            # Condition de succès : (URL step connue OU page différente de l'upload initial)
            # ET présence de champs éditables ET bouton Post détecté.
            on_description_page = (
                url_has_known_step
                or (has_editable and has_post_button)
            )

            if on_description_page and (has_input or has_editable) and has_post_button:
                state.update({
                    "has_title_field": bool(has_input),
                    "has_desc_field": bool(has_editable),
                    "has_post_button": True,
                })
                jlog("g2_5_redirect_validation_success", stage="g2_5_ultra", ui_state=state)
                return {'success': True, 'state': state}

            time.sleep(0.5)

        except Exception as e:
            jlog("g2_5_redirect_validation_error", stage="g2_5_ultra", error=str(e))
            time.sleep(0.5)

    jlog("g2_5_redirect_validation_timeout", stage="g2_5_ultra")
    return {'success': False, 'reason': 'timeout'}


# ---------------------------------------------------------------------------
# LOGIQUE D'UPLOAD — DOM.setFileInputFiles (ZERO-COPY NATIF)
# ---------------------------------------------------------------------------

def detect_drop_zone_intelligently(cd: CdpClient) -> Optional[dict]:
    """Diagnostic de la zone de drop avec priorité Darwinienne."""
    base_selectors = [
        '[data-e2e="upload-zone"]',
        '[data-e2e="drag-upload"]',
        '[data-intelligent-dropzone]',
        '.upload-drag-and-drop',
        'input[type="file"]',
    ]

    winner = DomDarwinCache.get_winner("drop_zone")
    if winner:
        if winner in base_selectors:
            base_selectors.remove(winner)
        base_selectors.insert(0, winner)

    check_script = r"""
    (selectors => {
      function isVisible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
               style.display !== 'none' && style.visibility !== 'hidden';
      }
      for (const sel of selectors) {
        const nodes = Array.from(document.querySelectorAll(sel));
        for (const el of nodes) {
          if (sel.includes('input') || isVisible(el)) {
             return { selector: sel, found: true };
          }
        }
      }
      return null;
    })
    """
    expr = f"({check_script})({json.dumps(base_selectors)})"
    try:
        res = cd.eval(expr, timeout=5.0)
        if not res:
            jlog("upload_interface_scan_failed", stage="g1")
            return None
        if res.get("found") and res.get("selector"):
            DomDarwinCache.save_winner("drop_zone", res["selector"])
        jlog("upload_interface_found", stage="g1", result=res)
        return res
    except Exception as e:
        jlog("upload_interface_scan_error", stage="g1", error=str(e))
        return None


def upload_via_dragdrop_intelligent(
    cd: CdpClient,
    filepath: Path,
    timeout_s: float = 20.0,
    max_mb: float = 256.0,
    latency: Optional[LatencyContext] = None,
) -> bool:
    """
    Upload natif via DOM.setFileInputFiles.
    FIX v5 : accepte LatencyContext, met à jour le facteur de latence.
    """
    lx = latency or _default_latency

    full_path = str(filepath.resolve())

    if not filepath.exists():
        jlog("upload_critical_error", stage="g1", error="File not found", path=full_path)
        return False

    jlog("upload_native_start", stage="g1", action="setFileInputFiles",
         ui_state={"file": filepath.name, "size_bytes": filepath.stat().st_size})

    try:
        start_time = time.monotonic()

        cd.send("DOM.enable")

        doc = cd.send("DOM.getDocument", {"depth": -1, "pierce": True})
        # Normalisation de la réponse CDP (peut être wrappé ou non dans "result")
        if "result" in doc and "root" in doc["result"]:
            root_id = doc["result"]["root"]["nodeId"]
        elif "root" in doc:
            root_id = doc["root"]["nodeId"]
        else:
            jlog("upload_doc_parse_error", stage="g1", error="Cannot find root nodeId", doc_keys=list(doc.keys()))
            return False

        input_selector = DomDarwinCache.get_winner("file_input") or "input[type='file']"

        node_res = cd.send("DOM.querySelector", {"nodeId": root_id, "selector": input_selector})
        if "result" in node_res:
            node_res = node_res["result"]

        if (not node_res or "nodeId" not in node_res) and input_selector != "input[type='file']":
            node_res = cd.send("DOM.querySelector", {
                "nodeId": root_id, "selector": "input[type='file']"
            })
            if "result" in node_res:
                node_res = node_res["result"]

        if not node_res or not node_res.get("nodeId"):
            jlog("upload_input_missing", stage="g1", error="No input[type='file'] found")
            return False

        DomDarwinCache.save_winner("file_input", "input[type='file']")
        file_input_node_id = node_res["nodeId"]

        cd.send("DOM.setFileInputFiles", {"files": [full_path], "nodeId": file_input_node_id})
        jlog("upload_native_files_set", stage="g1", action="files_assigned_to_node")

        wakeup_script = r"""
        (() => {
            const input = document.querySelector("input[type='file']");
            if (!input) return {fired: false, reason: 'no_input'};
            const evInput = new Event('input', { bubbles: true, cancelable: true });
            const evChange = new Event('change', { bubbles: true, cancelable: true });
            let fired = 0;
            if (input.dispatchEvent(evInput)) fired++;
            if (input.dispatchEvent(evChange)) fired++;
            return {fired: fired, inputs_found: 1};
        })()
        """

        time.sleep(0.5)
        res = cd.eval(wakeup_script, timeout=2.0)
        jlog("post_setfile_dispatch", stage="g1", action="dispatch_change_robust", ui_state=res)

        duration = time.monotonic() - start_time
        lx.update_from_duration(duration)

        return True

    except Exception as e:
        jlog("upload_native_exception", stage="g1",
             error_signature="cdp_native_upload_failed",
             decision_reason=str(e))
        return False