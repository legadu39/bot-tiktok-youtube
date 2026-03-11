### bot tiktok youtube/tools/tt_dom.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TikTok Uploader — Fonctions d'interaction DOM (CRITICAL MODE ++).
INTELLIGENCE V4: DOM Darwinism & Fuzzy Logic Centralized.
[NEW] Network-Aware Resilience (Dynamic Latency)

ARCHITECTURE: ZERO-COPY & NATIVE BINDING
"""

# Imports natifs
import json
import re
import time
import random
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING, List, Dict

# Imports du projet
from tt_cdp import CdpClient
from tt_utils import jlog

# Évite l'import circulaire pour les type hints
if TYPE_CHECKING:
    from tt_runner import UploadRunner

# --- CONSTANTES GLOBALES ---
# Basename neutre aléatoire par run pour éviter le fingerprinting par nom de fichier
NEUTRAL_BASENAME = f"nf_{random.randrange(16**8):08x}"

# [INTELLIGENCE] Facteur de latence global (Network-Aware)
# Ajusté dynamiquement après l'upload pour ralentir/accélérer le reste du script
CURRENT_LATENCY_FACTOR = 1.0

from tt_constants import TT_TMP_DIRNAME

# --- CONSTANTES JS (INTELLIGENCE HEURISTIQUE) ---

JS_FUZZY_CAPTION_SCAN = r"""
(function() {
    const candidates = document.querySelectorAll('div[contenteditable="true"], textarea, input[type="text"]');
    let bestEl = null;
    let maxScore = 0;
    let bestSelector = "";

    function generateSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.dataset.e2e) return `[data-e2e="${el.dataset.e2e}"]`;
        if (el.className) {
            // Prend la classe la plus spécifique qui n'a pas l'air générée aléatoirement
            const classes = el.className.split(' ').filter(c => c.length > 4 && !/\d/.test(c));
            if (classes.length > 0) return '.' + classes[0];
        }
        return el.tagName;
    }

    candidates.forEach(el => {
        let score = 0;
        const html = el.outerHTML.toLowerCase();
        const placeholder = (el.getAttribute('placeholder') || "").toLowerCase();
        const dataE2E = (el.getAttribute('data-e2e') || "").toLowerCase();
        const ariaLabel = (el.getAttribute('aria-label') || "").toLowerCase();
        const text = (el.innerText || el.value || "").toLowerCase();

        // Heuristiques positives (Probabilité d'être la Description)
        if (dataE2E.includes('caption') || dataE2E.includes('description')) score += 50;
        if (ariaLabel.includes('caption') || ariaLabel.includes('description') || ariaLabel.includes('légende')) score += 40;
        if (html.includes('mention') || html.includes('hashtag')) score += 20;
        if (placeholder.includes('tell us') || placeholder.includes('dites-nous') || placeholder.includes('describe')) score += 30;
        if (el.tagName === 'DIV' && el.getAttribute('contenteditable') === 'true') score += 15; // TikTok préfère les DIVs editables

        // Heuristiques négatives (Probabilité d'être autre chose)
        if (placeholder.includes('title') || placeholder.includes('titre')) score -= 50;
        if (dataE2E.includes('search')) score -= 100;
        if (el.getAttribute('type') === 'search') score -= 100;

        if (score > maxScore) {
            maxScore = score;
            bestEl = el;
            bestSelector = generateSelector(el);
        }
    });

    if (bestEl && maxScore > 20) {
        // On retourne un sélecteur utilisable si possible, sinon un index est trop fragile
        // Pour plus de robustesse, on peut tagger l'élément trouvé
        bestEl.setAttribute('data-nexus-target', 'true');
        return { found: true, score: maxScore, tag: bestEl.tagName, selector: bestSelector || '[data-nexus-target="true"]' };
    }
    return { found: false, best_score: maxScore };
})();
"""

# --- INTELLIGENCE V3: CACHE DARWINIEN ---

class DomDarwinCache:
    """
    Mémoire persistante pour les sélecteurs CSS.
    Retient quel sélecteur a fonctionné la dernière fois pour accélérer les futurs runs.
    """
    CACHE_FILE = Path("dom_darwin_cache.json")

    @classmethod
    def load(cls) -> dict:
        if not cls.CACHE_FILE.exists():
            return {}
        try:
            with open(cls.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Validation sommaire (expiration après 7 jours pour éviter les vieux sélecteurs morts)
                if time.time() - data.get("timestamp", 0) > 7 * 86400:
                    return {}
                return data.get("selectors", {})
        except Exception:
            return {}

    @classmethod
    def save_winner(cls, key: str, selector: str):
        """Enregistre un sélecteur gagnant pour une clé donnée (ex: 'upload_input')"""
        if not selector: return
        try:
            current = cls.load()
            current[key] = selector
            with open(cls.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": time.time(),
                    "selectors": current
                }, f, indent=2)
        except Exception:
            pass

    @classmethod
    def get_winner(cls, key: str) -> Optional[str]:
        return cls.load().get(key)

# -------------------------
# Gestion Système de Fichiers (Neutralisation)
# -------------------------

def _make_neutral_upload_copy(src_path: Path) -> str:
    """
    Crée une copie temporaire ou un lien symbolique avec un nom aléatoire
    pour éviter que le nom du fichier source ne fuite vers la plateforme.
    """
    p = Path(src_path)
    tmp_dir = p.parent / TT_TMP_DIRNAME
    tmp_dir.mkdir(exist_ok=True)
    
    # Utilisation du basename aléatoire
    dst = tmp_dir / f"{NEUTRAL_BASENAME}{p.suffix.lower()}"
    
    try:
        import shutil
        # On copie pour éviter les verrous fichiers, mais shutil.copy2 est optimisé
        shutil.copy2(p, dst)
        return str(dst)
    except Exception as e:
        jlog("neutral_copy_failed", stage="init", error=str(e))
        return str(p)  # Fallback sur le fichier original

# -------------------------
# Logique d'Upload (REWORK ZERO-COPY)
# -------------------------

def detect_drop_zone_intelligently(cd: CdpClient) -> Optional[dict]:
    """
    Diagnostic seulement. Utilise le cache Darwinien pour tester le dernier gagnant en premier.
    """
    # 1. Chargement des candidats
    base_selectors = [
        '[data-e2e="upload-zone"]',
        '[data-e2e="drag-upload"]',
        '[data-intelligent-dropzone]',
        '.upload-drag-and-drop',
        'input[type="file"]'
    ]
    
    # 2. Priorisation Darwinienne
    winner = DomDarwinCache.get_winner("drop_zone")
    if winner and winner in base_selectors:
        base_selectors.remove(winner)
        base_selectors.insert(0, winner)
    elif winner:
        base_selectors.insert(0, winner)

    check_script = r"""
    (selectors => {
      function isVisible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 &&
               rect.height > 0 &&
               style.display !== 'none' &&
               style.visibility !== 'hidden';
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
        
        # 3. Apprentissage (Sauvegarde du gagnant)
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
) -> bool:
    """
    PATCH 1 (CRITICAL MODE): UPLOAD NATIF ZERO-COPY
    [INTELLIGENCE] Mesure la vitesse pour ajuster le CURRENT_LATENCY_FACTOR
    """
    global CURRENT_LATENCY_FACTOR
    
    full_path = str(filepath.resolve())
    
    if not filepath.exists():
        jlog("upload_critical_error", stage="g1", error="File not found", path=full_path)
        return False
        
    jlog("upload_native_start", stage="g1", action="setFileInputFiles", 
         ui_state={"file": filepath.name, "size_bytes": filepath.stat().st_size})

    try:
        start_time = time.monotonic() # Début mesure latence

        cd.send("DOM.enable")
        
        doc = cd.send("DOM.getDocument", {"depth": -1, "pierce": True})
        root_id = doc["root"]["nodeId"]
        
        # INTELLIGENCE: On cherche d'abord avec le sélecteur cached, sinon standard
        input_selector = DomDarwinCache.get_winner("file_input") or "input[type='file']"
        
        node_res = cd.send("DOM.querySelector", {
            "nodeId": root_id,
            "selector": input_selector
        })
        
        # Fallback si le cache a échoué
        if (not node_res or "nodeId" not in node_res) and input_selector != "input[type='file']":
            node_res = cd.send("DOM.querySelector", {
                "nodeId": root_id,
                "selector": "input[type='file']"
            })

        if not node_res or "nodeId" not in node_res:
            jlog("upload_input_missing", stage="g1", error="No input[type='file'] found")
            return False
        else:
            # Succès : on confirme ce sélecteur comme bon (même si c'est le standard)
            DomDarwinCache.save_winner("file_input", "input[type='file']")

        file_input_node_id = node_res["nodeId"]

        cd.send("DOM.setFileInputFiles", {
            "files": [full_path],
            "nodeId": file_input_node_id
        })
        
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
        
        # [INTELLIGENCE] Calcul du facteur de latence
        end_time = time.monotonic()
        duration = end_time - start_time
        # Si ça a pris plus de 2 secondes, on considère que le système/réseau lag
        # On ajuste le facteur global (borné entre 1.0 et 5.0)
        expected_fast_time = 1.0
        if duration > expected_fast_time:
            CURRENT_LATENCY_FACTOR = min(5.0, duration / expected_fast_time)
            jlog("network_aware", msg=f"🐢 Ralentissement détecté ({duration:.2f}s). Latency Factor ajusté à {CURRENT_LATENCY_FACTOR:.2f}x")
        else:
            CURRENT_LATENCY_FACTOR = 1.0
            jlog("network_aware", msg="🚀 Système réactif. Latency Factor = 1.0x")

        return True

    except Exception as e:
        jlog("upload_native_exception", stage="g1", 
             error_signature="cdp_native_upload_failed", 
             decision_reason=str(e))
        return False

# -------------------------
# G3 Robust Utilities (PATCH V2 & 5)
# -------------------------

FILENAME_PREFILL_RE = re.compile(
    rf"^\s*(?:\d{{8}}T\d{{6}}[_\w-]|{NEUTRAL_BASENAME}|video|vid[eé]o|clip|movie)\s*",
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

def guard_mutation_js(selector_json: str, desired_json: str, ms: int=1500) -> str:
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
    try {{
        document.execCommand('insertText', false, {desired_json});
        return {{ok:true}};
    }} catch(e) {{
        return {{ok:false, why:'exec_failed'}};
    }}
    }})();
    """

def _native_setter_js(selector_json: str, desired_json: str) -> str:
    return f"""
    (function(){{
    const el = document.querySelector({selector_json});
    if(!el) return {{ok:false, why:'not_found'}};
    try {{
        el.focus();
        if (el.value !== undefined) {{
            const desc = Object.getOwnPropertyDescriptor(el.proto || HTMLInputElement.prototype, 'value')
            || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
            if (desc && desc.set) desc.set.call(el, {desired_json}); else el.value = {desired_json};
        }} else {{
            el.textContent = {desired_json};
        }}
        el.dispatchEvent(new Event('input', {{bubbles:true, cancelable:true}}));
        el.dispatchEvent(new Event('change', {{bubbles:true, cancelable:true}}));
        return {{ok:true}};
    }} catch(e) {{
        return {{ok:false, why:'setter_failed'}};
    }}
    }})();
    """

# --- INTELLIGENCE N°2: RESOLUTION DYNAMIQUE ---

def resolve_caption_selector_smart(runner: 'UploadRunner') -> str:
    """
    Tente de trouver le meilleur sélecteur pour la description.
    1. Regarde le Cache Darwinien.
    2. Si échec, lance le Fuzzy Scan.
    3. Met à jour le Cache si succès.
    """
    # 1. Cache
    cached = DomDarwinCache.get_winner("caption_input")
    if cached:
        # Vérification rapide si l'élément existe toujours
        check_js = f"!!document.querySelector({json.dumps(cached)})"
        if runner.eval(check_js, True, 1.0):
            jlog("dom_resolution", strategy="cache_hit", selector=cached)
            return cached
    
    # 2. Fuzzy Scan
    jlog("dom_resolution", strategy="fuzzy_scan_start")
    res = runner.eval(JS_FUZZY_CAPTION_SCAN, True, 2.0) or {}
    
    if res.get("found") and res.get("selector"):
        winner = res["selector"]
        jlog("dom_resolution", strategy="fuzzy_success", score=res.get("score"), selector=winner)
        DomDarwinCache.save_winner("caption_input", winner)
        return winner
    
    # 3. Fallback Hardcodé (Dernier recours)
    fallback = '[data-e2e*="caption"] div[contenteditable="true"]'
    jlog("dom_resolution", strategy="fallback_static", selector=fallback)
    return fallback

def set_description_robust(runner: 'UploadRunner', desc_selector_used: str, description: str,
                           max_attempts: int = 6, base_sleep: float = 0.18,
                           stable_reads: int = 4, stable_interval_s: float = 0.28,
                           guard_ms: int = 2500) -> bool:
    """
    Tente de définir la description avec une stratégie en couches (CDP -> DOM -> Native).
    INTELLIGENCE : Si desc_selector_used est None ou 'auto', on résout dynamiquement.
    [NEW] Utilisation du CURRENT_LATENCY_FACTOR.
    """
    
    # Ajustement Latence
    base_sleep *= CURRENT_LATENCY_FACTOR
    stable_interval_s *= CURRENT_LATENCY_FACTOR
    
    # Résolution Dynamique si demandé
    if not desc_selector_used or desc_selector_used == "auto":
        desc_selector_used = resolve_caption_selector_smart(runner)

    sel_j = json.dumps(desc_selector_used)
    desired_j = json.dumps(description)

    try:
        runner.eval(guard_mutation_js(sel_j, desired_j, guard_ms), True, 2.0 * CURRENT_LATENCY_FACTOR)
    except Exception as e:
        jlog("g3_mutation_guard_failed", stage="g3", error=str(e))

    def _read_norm():
        try:
            got = runner.eval(_reads_caption_js(sel_j), True, 2.0 * CURRENT_LATENCY_FACTOR) or {}
            raw = (got.get("text") if isinstance(got, dict) else "") or ""
            return _normalize(raw)
        except Exception as e:
            jlog("g3_readback_failed", stage="g3", error=str(e))
            return ""

    want = _normalize(description)
    
    for i in range(max_attempts):
        try:
            runner.eval(_select_all_js(sel_j), True, 2.0 * CURRENT_LATENCY_FACTOR)
        except Exception as e:
            jlog("g3_select_all_failed", stage="g3", attempt=i, error=str(e))
        
        time.sleep(0.08 * CURRENT_LATENCY_FACTOR)

        cdp_ok = True
        try:
            runner.cd.send("Input.insertText", {"text": description}, timeout=10.0 * CURRENT_LATENCY_FACTOR)
        except Exception as e:
            cdp_ok = False
            jlog("g3_insertText_cdp_failed", stage="g3", attempt=i, error=str(e))

        if not cdp_ok:
            try:
                runner.eval(_dom_insert_text_js(sel_j, desired_j), True, 2.0 * CURRENT_LATENCY_FACTOR)
            except Exception as e:
                 jlog("g3_insertText_dom_failed", stage="g3", attempt=i, error=str(e))

        txt = _read_norm()
        if txt != want or FILENAME_PREFILL_RE.match(txt or ""):
            try:
                runner.eval(_native_setter_js(sel_j, desired_j), True, 2.0 * CURRENT_LATENCY_FACTOR)
            except Exception as e:
                 jlog("g3_insertText_setter_failed", stage="g3", attempt=i, error=str(e))

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
                runner.eval(f"(function(){{const el=document.querySelector({sel_j}); if(el) el.blur(); }})()", True, 1.0)
            except Exception:
                pass
            jlog("g3_set_desc_validate_ok", stage="g3", attempt=i, read_len=len(txt))
            return True

        try:
            runner.cd.send("Input.dispatchKeyEvent", {"type":"keyDown","modifiers":2,"key":"a","code":"KeyA","windowsVirtualKeyCode":65,"nativeVirtualKeyCode":65})
            runner.cd.send("Input.dispatchKeyEvent", {"type":"keyUp","modifiers":2,"key":"a","code":"KeyA","windowsVirtualKeyCode":65,"nativeVirtualKeyCode":65})
        except Exception:
            pass
            
        time.sleep(base_sleep * (1 + i/3.0))

    return False

def revalidate_caption_before_post(runner: 'UploadRunner', desc_selector_used: str, description: str) -> bool:
    """Vérification finale pré-publication"""
    
    # Sécurité: si le sélecteur n'est pas fourni, on tente de le résoudre, 
    # mais à ce stade (G5), on préfère utiliser celui qui a marché en G3.
    if not desc_selector_used or desc_selector_used == "auto":
        desc_selector_used = resolve_caption_selector_smart(runner)

    sel_j = json.dumps(desc_selector_used)
    want = _normalize(description)

    def stable_ok():
        ok = 0
        for _ in range(4):
            time.sleep(0.28 * CURRENT_LATENCY_FACTOR)
            try:
                got = runner.eval(_reads_caption_js(sel_j), True, 2.0 * CURRENT_LATENCY_FACTOR) or {}
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
    if set_description_robust(runner, desc_selector_used, description, max_attempts=3, guard_ms=2000):
        if stable_ok():
             jlog("g5_revalidation_correction_ok", stage="g5", action="pre_post_correction_success")
             return True

    jlog("g5_revalidation_failed_blocking", stage="g5", action="abort_post")
    return False

# -------------------------
# Fonctions de validation (G2.5)
# -------------------------

def capture_page_state_hash() -> dict:
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

def find_and_click_next_button(runner: 'UploadRunner', max_retries: int = 3, timeout_between_retries: float = 2.0) -> bool:
    jlog("g2_5_next_button_search", stage="g2_5_ultra", action="start")

    try:
        pre_state = runner._eval(capture_page_state_hash(), timeout=5 * CURRENT_LATENCY_FACTOR) or {}
        current_url = pre_state.get('url', '')
        
        is_on_upload_route = ("/upload" in current_url) or ("tiktokstudio/upload" in current_url)
        
        if not is_on_upload_route:
            jlog("g2_5_precondition_failed", stage="g2_5_ultra", decision_reason="Wrong URL context")
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
            return { found: true, strategy: 'text_match', selector: candidates[0].className };
        }
        
        candidates = [...document.querySelectorAll('button[data-testid*="next" i], button[aria-label*="next" i]')].filter(vis);
        if (candidates.length > 0) {
            return { found: true, strategy: 'data_testid_next', selector: candidates[0].getAttribute('data-testid') };
        }
        
        return { found: false };
    })();
    """
    
    for attempt in range(max_retries):
        try:
            discovery = runner._eval(find_next_script, timeout=5 * CURRENT_LATENCY_FACTOR) or {}
            
            if not discovery.get('found'):
                if attempt < max_retries - 1:
                    time.sleep(timeout_between_retries * CURRENT_LATENCY_FACTOR)
                continue
            
            jlog("g2_5_next_button_detected", stage="g2_5_ultra", ui_state=discovery)
            
            # INTELLIGENCE: On pourrait sauver le sélecteur gagnant ici aussi
            if discovery.get('strategy') == 'data_testid_next':
                DomDarwinCache.save_winner("next_button", discovery.get('selector'))
            
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
                    button = [...document.querySelectorAll('button[data-testid*="next" i], button[aria-label*="next" i]')].find(vis);
                }
                
                if (!button) return { clicked: false };
                
                button.scrollIntoView({ behavior: 'smooth', block: 'center' });
                await new Promise(r => setTimeout(r, 500));
                button.click();
                return { clicked: true };
            })();
            """
            
            click_result = runner._eval(click_script, timeout=10 * CURRENT_LATENCY_FACTOR) or {}
            
            if click_result.get('clicked'):
                jlog("g2_5_next_button_clicked", stage="g2_5_ultra")
                time.sleep(2.0 * CURRENT_LATENCY_FACTOR)
                return True
            
        except Exception as e:
            jlog("g2_5_next_button_exception", stage="g2_5_ultra", error=str(e))
            
    return False

def validate_redirect_to_description_page(runner: 'UploadRunner', expected_params: list = None, timeout_s: float = 20.0) -> dict:
    if expected_params is None:
        expected_params = ['step=description', 'step=edit', 'step=details']
    
    # Ajustement Timeout dynamique
    adjusted_timeout = timeout_s * CURRENT_LATENCY_FACTOR
    jlog("g2_5_redirect_validation_start", stage="g2_5_ultra", timeout_adjusted=adjusted_timeout)
    
    t0 = time.monotonic()
    
    while (time.monotonic() - t0) < adjusted_timeout:
        try:
            state = runner._eval(capture_page_state_hash(), timeout=5 * CURRENT_LATENCY_FACTOR) or {}
            current_url = state.get('url', '')
            
            url_ok = any(param in current_url for param in expected_params) or \
                     ("/tiktokstudio/upload" in current_url and "step=" not in current_url)
            
            if not url_ok:
                time.sleep(0.5)
                continue
            
            has_title_field = state.get('has_title_input') or state.get('has_contenteditable')
            has_desc_field = state.get('has_contenteditable') or state.get('has_textarea')
            
            has_post_button = runner._eval(r"""
            (() => {
                const btns = [...document.querySelectorAll('button')];
                return !!btns.find(b => /^(post|publier)$/i.test((b.innerText || b.textContent || '').trim()));
            })()
            """, timeout=5 * CURRENT_LATENCY_FACTOR) or False
            
            if has_title_field and has_desc_field and has_post_button:
                state.update({
                    "has_title_field": True,
                    "has_desc_field": True,
                    "has_post_button": True
                })
                jlog("g2_5_redirect_validation_success", stage="g2_5_ultra", ui_state=state)
                return {'success': True, 'state': state}
            
            time.sleep(0.5)
            
        except Exception as e:
            time.sleep(0.5)
    
    jlog("g2_5_redirect_validation_timeout", stage="g2_5_ultra")
    return {'success': False, 'reason': 'timeout'}