# gemini_headless/collect/producers/dom.py
# CORRIGÉ V7.12-FINAL (Playwright API Fix + JS Robustesse + Timeout Fix)
# - FIX: Correction safe_frame_evaluate (retrait kwarg timeout)
# - FIX: Utilisation correcte asyncio.wait_for() AUTOUR de safe_frame_evaluate
# - FIX: Encapsulation JS (SCROLL_JS, _GET_BEST_TEXT_JS) en IIFE try/catch
#
# ✅ PATCH ORCHESTRATOR BLINDNESS (DOM PULL ACTIF) APPLIQUÉ
# - snapshot_now() retourne maintenant un dict {"text": ..., "meta": ...}
# - snapshot_now() est encapsulé dans un try/except global pour la robustesse.
#
# ⭐️⭐️⭐️ PATCH CORRECTIF (BLINDNESS V2) APPLIQUÉ ⭐️⭐️⭐️
# - La fonction `isVisible` dans _GET_BEST_TEXT_JS a été modifiée
#
# ✅ PATCH END-TO-END (DOM RESILIENCE) APPLIQUÉ
# - _SCROLL_JS mis à jour pour trouver le scroller de chat (main[role='feed']).
#
# 🚀 INTELLIGENCE ADDITIONNELLE (ADAPTIVE & PREDICTIVE) :
# - SCROLL FEEDBACK LOOP : Le scroll retourne le delta pour ajuster la vitesse (PID Controller simple).
# - SELECTOR LEARNING : _GET_BEST_TEXT_JS apprend et priorise les sélecteurs qui fonctionnent (window.validSelectors).
# - CONTEXT STABILIZATION : Hystérésis conservé pour éviter le scintillement.
#

from __future__ import annotations
import asyncio, time, re, json
from typing import Callable, Optional, List, Dict, Any, Tuple
from playwright.async_api import Page, Frame, Error as PlaywrightError
import os

# --- Dépendances pour la compatibilité Playwright ---
try:
    from packaging import version
    import playwright
    PW_VERSION = version.parse(playwright.__version__)
    FRAME_EVALUATE_USES_OLD_SIGNATURE = PW_VERSION < version.parse("1.45.0")
except (ImportError, AttributeError, ValueError):
    FRAME_EVALUATE_USES_OLD_SIGNATURE = False

async def safe_frame_evaluate(frame: Frame, script: str, *args) -> Any:
    """
    Wrapper pour Frame.evaluate() compatible Playwright < 1.45 et >= 1.45.

    ⚠️ NE PAS passer timeout ici - le gérer avec asyncio.wait_for() autour!
    """
    try:
        if FRAME_EVALUATE_USES_OLD_SIGNATURE and len(args) >= 1:
            # Ancienne API Playwright (< 1.45): passer args directement
            return await frame.evaluate(script, *args)
        else:
            # Nouvelle API Playwright (>= 1.45): encapsuler args
            if len(args) == 1:
                return await frame.evaluate(script, args[0])
            elif len(args) > 1:
                # Plusieurs args: envoyer comme liste
                return await frame.evaluate(script, args)
            else:
                # Sans args
                return await frame.evaluate(script)

    except TypeError as te:
        # Fallback graceful: essayer sans args
        try:
            return await frame.evaluate(script)
        except TypeError:
            jlog(
                "safe_frame_evaluate_crash",
                error=str(te).split('\n')[0],
                level="ERROR"
            )
            raise

    except Exception as e:
        jlog(
            "safe_frame_evaluate_crash",
            error=str(e).split('\n')[0],
            level="ERROR"
        )
        raise

try:
    from ...utils.logs import jlog  # package
except Exception:
    try:
        from utils.logs import jlog  # script direct
    except Exception:
        import sys
        def jlog(evt: str, **kw):
            try:
                import json as _json
                payload = {"evt": evt, **kw}
                print(_json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr)
                sys.stderr.flush()
            except Exception:
                print(f'{{"evt":"jlog_fallback","msg":"{evt}"}}', file=sys.stderr)


# Runtime toggles
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip().lower()
    return (v in {"1","true","yes","on","y"}) if v else default
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

GH_DOM_SCROLL_ENABLE = _env_bool("GH_DOM_SCROLL_ENABLE", True)
GH_DOM_SCROLL_STEPS = _env_int("GH_DOM_SCROLL_STEPS", 6)
GH_DOM_SCROLL_DELAY_MS = _env_int("GH_DOM_SCROLL_DELAY_MS", 120)

GH_DOM_MINIDUMP_ON_EMPTY = _env_bool("GH_DOM_MINIDUMP_ON_EMPTY", True)
GH_DOM_MINIDUMP_MAX = _env_int("GH_DOM_MINIDUMP_MAX", 5)


# --- PATCH #2 + INTELLIGENCE #3 : SCROLLJS robuste avec Feedback Loop ---
_SCROLL_JS = r"""
async (args) => {
    try {
        const scrollFunc = (async (direction_arg, steps_arg, delayMs_arg) => {
            try {
                const findScroller = () => {
                  const cands = document.querySelectorAll("main [role='feed'], main [aria-live], [aria-live]");
                  for (const el of cands) {
                    const st = getComputedStyle(el);
                    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight) return el;
                  }
                  return document.scrollingElement || document.documentElement || document.body;
                };
                const root = findScroller();
                
                if (!root) return {scrolled: false, delta: 0};

                const dir = (direction_arg + "").toLowerCase();
                const stepCount = Math.max(1, parseInt(steps_arg) || 3);
                const delay = Math.max(0, parseInt(delayMs_arg) || 120);

                const viewH = window.innerHeight || 800;
                const scrollDelta = Math.floor(viewH * 0.85);
                
                let totalMoved = 0;
                const startTop = root.scrollTop;

                for (let i = 0; i < stepCount; i++) {
                    const prevTop = root.scrollTop;
                    const y = prevTop + (dir === "down" ? scrollDelta : -scrollDelta);
                    root.scrollTo({ top: y, behavior: "instant" });

                    if (delay > 0) {
                        await new Promise(r => setTimeout(r, delay));
                    }
                    
                    const currentTop = root.scrollTop;
                    const moved = Math.abs(currentTop - prevTop);
                    totalMoved += moved;

                    // INTELLIGENCE: Arrêt précoce si bloqué/fin de page
                    if (moved < 1) {
                        break; 
                    }
                }
                
                // Retourne info enrichie pour boucle de feedback Python
                return {
                    scrolled: true, 
                    delta: totalMoved,
                    newTop: root.scrollTop,
                    maxTop: root.scrollHeight - root.clientHeight
                };
            } catch (innerErr) {
                return {scrolled: false, error: innerErr.toString()};
            }
        });

        // Arguments[0] est un array/list Python dans le nouveau Playwright API
        const unpack = Array.isArray(args) ? args : (args ? [args] : []);
        return await scrollFunc(unpack[0], unpack[1], unpack[2]);
    } catch (outerErr) {
        return {scrolled: false, error: outerErr.toString()};
    }
}
"""

# === DEBUT PATCH (Remplacement _MINIDUMP_JS) ===
_MINIDUMP_JS = r"""
() => {
  try {
    const takeHead = (s, n=200) => (s||"").replace(/\s+/g," ").trim().slice(0,n);
    const sels = [
      "[data-message-author='assistant']",
      "article[data-author='assistant']",
      "[data-message-author]",
      "article",
      ".model-response-text",
      ".response-content-container",
      "[aria-live]"
    ];
    const nodes = [];
    for (const sel of sels) {
      const arr = Array.from(document.querySelectorAll(sel));
      for (let i=arr.length-1;i>=0;i--) nodes.push(arr[i]); // récent -> ancien
    }
    const out = [];
    const seen = new Set();
    for (let i=0;i<nodes.length && out.length < 12;i++){
      const el = nodes[i];
      if (!el || !el.isConnected) continue;
      if (seen.has(el)) continue;
      seen.add(el);
      let txt = "";
      try {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
        let node; let buf = "";
        while ((node = walker.nextNode())) {
          const t = (node.nodeValue || "").replace(/\s+/g, " ").trim();
          if (t) buf = buf ? buf + " " + t : t;
        }
        txt = buf || (el.innerText || el.textContent || "");
      } catch(_) {
        txt = (el.innerText || el.textContent || "");
      }
      txt = (txt || "").trim();
      if (txt && txt.length >= 10) out.push({ len: txt.length, head: takeHead(txt), full: txt });
    }
    out.sort((a,b) => (b.len||0) - (a.len||0));
    const uniq = []; const memo = new Set();
    for (const it of out) {
      const h = it.head;
      if (!memo.has(h)) { memo.add(h); uniq.push(it); }
      if (uniq.length >= 8) break;
    }
    return uniq.slice(0, 5);
  } catch(e){ return []; }
}
"""
# === FIN PATCH ===


# --- PATCH VISION + INTELLIGENCE #4 : GETBESTTEXTJS avec Images et Contextual Stabilization ---
# Changement de signature: (async function(){...})() -> async (args) => {...} pour accepter prevHead
_GET_BEST_TEXT_JS = r"""
async (args) => {
    try {
        const unpack = Array.isArray(args) ? args : (args ? [args] : []);
        const prevHeadArg = unpack[0] || null;

        // --- Helpers ---
        const isVisible = (el) => {
            try {
                if (!el || !el.isConnected) return false;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                const s = getComputedStyle(el);
                if (s.visibility === "hidden" || s.display === "none" || s.opacity === "0") return false;
                return true;
            } catch (e) { return false; }
        };
        
        const deepTextContent = (el) => {
            try {
                let s = "";
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
                let node;
                while ((node = walker.nextNode())) {
                    const t = (node.nodeValue || "").replace(/\s+/g, " ").trim();
                    if (t) s = s ? s + " " + t : t;
                }
                return s || (el.textContent || "").replace(/\s+/g, " ").trim();
            } catch (e) { return (el.textContent || "").replace(/\s+/g, " ").trim(); }
        };

        const extractImages = (rootEl) => {
            const images = [];
            if (!rootEl) return images;
            let candidates = Array.from(rootEl.querySelectorAll('img'));
            if (candidates.length === 0 && rootEl.parentElement) {
                 const siblings = Array.from(rootEl.parentElement.querySelectorAll('img'));
                 siblings.forEach(img => candidates.push(img));
            }
            const seenUrls = new Set();
            const validImages = [];
            for (const img of candidates) {
                if (!isVisible(img)) continue;
                const src = img.src || img.getAttribute('src');
                if (!src || src.startsWith('data:') || src.includes('googleusercontent.com/.../icon')) continue; 
                const rect = img.getBoundingClientRect();
                const natW = img.naturalWidth || 0;
                const natH = img.naturalHeight || 0;
                const isBigEnough = (rect.width > 150 && rect.height > 150) || (natW > 150 && natH > 150);
                if (isBigEnough) {
                    if (!seenUrls.has(src)) {
                        seenUrls.add(src);
                        validImages.push({
                            url: src,
                            alt: img.alt || "Generated Image",
                            width: Math.max(rect.width, natW),
                            height: Math.max(rect.height, natH)
                        });
                    }
                }
            }
            return validImages;
        };

        // --- INTELLIGENCE: Selector Auto-Optimization ---
        // On initialise un scoreboard global si inexistant
        if (!window._gemini_selector_scores) {
            window._gemini_selector_scores = {}; 
        }

        const BASE_SELS = [
            "[data-message-author='assistant']:not([aria-busy='true']) .model-response-text",
            "[data-message-author='assistant']:not([aria-busy='true']) [role='article']",
            "article[data-author='assistant']",
            ".model-response-text",
            ".response-content-container",
            "main [role='feed'] article",
            ".prose", ".markdown"
        ];
        
        // Tri dynamique: ceux avec un score élevé en premier
        const SORTED_SELS = [...BASE_SELS].sort((a,b) => {
             return (window._gemini_selector_scores[b] || 0) - (window._gemini_selector_scores[a] || 0);
        });

        // Ajoute un sélecteur générique pour la fin de liste
        const ALL_SELS = SORTED_SELS.join(',');
        
        const zones = Array.from(document.querySelectorAll('main, [role="main"], [aria-live], body')) || [document.body];
        let best = null, bestScore = -1;
        let bestSelectorUsed = null;

        for (const zone of zones) {
             try { 
                if (!zone || !zone.isConnected) continue;
                const cands = Array.from(zone.querySelectorAll(ALL_SELS));
                if (zone.matches('div, section, article') && isVisible(zone)) cands.push(zone);

                for (let i = cands.length - 1; i >= 0; i--) {
                     try { 
                        const n = cands[i];
                        if (!n || !n.isConnected) continue; 
                        
                        let isAssistant = true;
                        try {
                            const closest = n.closest("[data-message-author],[data-author]");
                            const auth = closest ? (closest.getAttribute("data-message-author") || closest.getAttribute("data-author")) : "assistant";
                            isAssistant = (auth !== "user");
                        } catch(e) {}
                        if (!isAssistant) continue;
                        
                        let t = "";
                        try { t = deepTextContent(n); } catch(_) { t = (n.textContent || "").trim(); }
                        const len = (t || "").length;
                        if (len == 0 && isVisible(n) == false) continue;

                        let score = 0;
                        if (len > 50) score += 20 + Math.min(len / 50, 20);
                        if (n.querySelectorAll('img').length > 0) score += 15;

                        // INTELLIGENCE : STABILISATION (Hystérésis)
                        // Si le texte commence comme celui de la dernière fois, bonus énorme
                        if (prevHeadArg && t.startsWith(prevHeadArg)) {
                            score += 50;
                        }

                        if (score > bestScore) { 
                            bestScore = score; 
                            best = n; 
                            // Tente de deviner quel sélecteur a matché pour le scoring
                            for(const s of BASE_SELS) {
                                if (n.matches(s)) { bestSelectorUsed = s; break; }
                            }
                        }
                    } catch (candErr) { }
                }
            } catch (zoneErr) { }
        }

        let el = best;
        if (!el) {
             const fallbacks = [".model-response-text", "article"];
             for(const sel of fallbacks) {
                 const found = document.querySelector(sel);
                 if(found && isVisible(found)) { 
                     el = found; 
                     bestSelectorUsed = sel;
                     break; 
                 }
             }
        }

        if (!el) return {text: "", images: []};

        // INTELLIGENCE: Mise à jour du Scoreboard si succès
        if (bestSelectorUsed && window._gemini_selector_scores) {
             window._gemini_selector_scores[bestSelectorUsed] = (window._gemini_selector_scores[bestSelectorUsed] || 0) + 1;
        }

        let text = "";
        try { text = deepTextContent(el); } catch(e){ text = (el.textContent || "").trim(); }
        const images = extractImages(el);

        return {
            text: (text || "").trim(),
            images: images
        };

    } catch(e) {
        return {text: "", images: [], error: e.toString()};
    }
}
"""


class DOMProducer:
    """Producteur DOM (V7.12 - Sélecteurs étendus, priorité JSON+<<END>>, JS robuste, Vision)."""

    def __init__(self, page: Page, on_progress: Callable[[str], None], on_done: Callable[[str, Optional[str]], None]):
        self.page = page
        self.on_progress_cb = on_progress
        self.on_done_cb = on_done
        self.seen: bool = False
        self.done: bool = False
        self._last_full_text: str = ""
        self._last_images_seen: List[Dict[str, Any]] = []
        # INTELLIGENCE : Persistance pour hystérésis
        self._last_best_head: Optional[str] = None
        # INTELLIGENCE : Tracking scroll velocity pour adaptive sleep
        self._last_text_len = 0
        self._last_snapshot_ts = 0.0

    async def start(self) -> None:
        """Vérifie que les fonctions JS (V7.12) sont évaluables (prewarm)."""
        if self.page.is_closed():
            jlog("dom_start_fail_page_closed_v7.11", level="WARN")
            return
        try:
            await asyncio.wait_for(self.page.evaluate("() => 1+1"), timeout=1.2)
            jlog("dom_start_prewarm_ok_v7.11")
        except Exception as e:
            jlog("dom_start_prewarm_error_v7.11", error=str(e), level="WARN")

    async def stop(self) -> None:
        self.done = True
        jlog("dom_stop_v7.11")
        self.seen = False
        self.done = False # Reset state
        self._last_best_head = None
        self._last_text_len = 0

    async def snapshot_now(self) -> dict:
        """Extraction cross-frames : retourne le meilleur texte via JS V7.12 robuste (BFS frames)."""
        best_text = ""
        final_len = 0
        t_start_snap = time.monotonic()
        jlog("snapshot_now_start_v7.11", strategy="evaluate_best_text_js_bfs")
        page_closed_logged = False
        
        # INTELLIGENCE: Adaptive Sleep par défaut (standard)
        suggested_sleep = 0.1 

        try: # Wrapper try/except global demandé par le patch
            frames_to_check: List[Frame] = []
            try:
                if self.page.is_closed():
                    jlog("snapshot_now_page_closed_at_start_v7.11", level="WARN")
                    raise PlaywrightError("Page closed at start of snapshot")
                main_frame = self.page.main_frame
                if not main_frame or main_frame.is_detached():
                    jlog("snapshot_now_main_frame_detached_or_invalid_v7.11", level="WARN")
                    raise PlaywrightError("Main frame detached or invalid")

                queue: List[Frame] = [main_frame]
                seen_ids: set = set()
                while queue:
                    fr = queue.pop(0)
                    fid = id(fr) # Use simple ID for seen check
                    if fid in seen_ids: continue
                    seen_ids.add(fid)
                    if not fr.is_detached(): # Check detachment before adding
                        frames_to_check.append(fr)
                        try:
                            children = [cf for cf in fr.child_frames if cf and not cf.is_detached()]
                            queue.extend(children)
                        except Exception as child_err:
                            jlog("snapshot_now_child_frame_list_error_v7.11", error=str(child_err), level="WARN")

                jlog("snapshot_now_frames_to_check_v7.11", count=len(frames_to_check))
            except Exception as frame_err:
                jlog("snapshot_now_frame_access_error_v7.11", error=str(frame_err), error_type=type(frame_err).__name__, level="ERROR")
                raise # Propager à l'catch externe

            for idx, fr in enumerate(frames_to_check):
                frame_label = "main" if idx == 0 else f"child_{idx}"
                if self.page.is_closed():
                    if not page_closed_logged: jlog("snapshot_now_page_closed_during_iteration_v7.11", level="WARN"); page_closed_logged = True
                    break
                if fr.is_detached():
                    jlog("snapshot_now_skip_detached_frame_v7.11", frame=frame_label, frame_url=fr.url, level="DEBUG")
                    continue

                # --- Scroll Attempt (avec Feedback Loop) ---
                if GH_DOM_SCROLL_ENABLE:
                    try:
                        scroll_res = await asyncio.wait_for(
                            safe_frame_evaluate(
                                fr,
                                _SCROLL_JS, # Version robuste + feedback loop
                                ["down", GH_DOM_SCROLL_STEPS, GH_DOM_SCROLL_DELAY_MS]
                            ),
                            timeout=4.5
                        )
                        # INTELLIGENCE: Feedback Loop du Scroll
                        if isinstance(scroll_res, dict) and scroll_res.get("scrolled"):
                            delta = scroll_res.get("delta", 0)
                            # Si on scrolle beaucoup, on réduit le délai
                            if delta > 100: 
                                suggested_sleep = 0.05
                            elif delta < 5:
                                suggested_sleep = 0.2 # Bloqué ou fin, on ralentit
                        
                        await asyncio.sleep(0.05)
                    except asyncio.TimeoutError:
                         jlog("snapshot_now_scroll_timeout_v7.11", frame=frame_label, level="DEBUG")
                    except Exception as scroll_err:
                         jlog("snapshot_now_scroll_error_v7.11", frame=frame_label, frame_url=fr.url, error=str(scroll_err), level="DEBUG")

                # --- Text & Image Evaluation (avec Stabilisation) ---
                try:
                    js_expr = _GET_BEST_TEXT_JS
                    # INTELLIGENCE: On passe la signature (début) du texte précédent pour l'hystérésis
                    prev_head_arg = self._last_best_head[:50] if self._last_best_head else None
                    
                    result_data = await asyncio.wait_for(
                        safe_frame_evaluate(fr, js_expr, [prev_head_arg]), 
                        timeout=5.0 
                    )
                    
                    if isinstance(result_data, str):
                        result_data = {"text": result_data, "images": []}
                    
                    txt = result_data.get("text", "")
                    imgs = result_data.get("images", [])
                    
                    t_strip = (txt or "").strip()
                    if t_strip:
                        # Logique de sélection
                        is_json = (t_strip.endswith("<<END>>") or t_strip.endswith("<>")) and t_strip.startswith("{")
                        
                        if is_json or len(t_strip) > len(best_text):
                            best_text = t_strip
                            
                            self._last_images_seen = imgs 
                            if imgs:
                                jlog("snapshot_now_images_found", count=len(imgs), frame=frame_label)
                            
                            if is_json: break 

                except asyncio.TimeoutError:
                    jlog("snapshot_now_eval_timeout_v7.11", frame=frame_label, frame_url=fr.url, level="WARN")
                except PlaywrightError as pw_err:
                    err_str = str(pw_err).lower()
                    short_err = err_str.split('\n')[0]
                    is_context_destroyed = ("target closed" in err_str or "frame was detached" in err_str or "context was destroyed" in err_str)
                    if is_context_destroyed: jlog("snapshot_now_eval_context_destroyed_v7.11", frame=frame_label, frame_url=fr.url, error=short_err, level="WARN"); break
                    else: jlog("snapshot_now_eval_playwright_error_v7.11", frame=frame_label, frame_url=fr.url, error=short_err, level="WARN")
                except Exception as eval_err:
                    short_err = str(eval_err).split('\n')[0]
                    jlog("snapshot_now_eval_unexpected_error_v7.11", frame=frame_label, frame_url=fr.url, error=short_err, error_type=type(eval_err).__name__, level="ERROR")

            final_len = len(best_text)
            
            # INTELLIGENCE: Mémorisation pour le prochain cycle (Hystérésis)
            if final_len > 10:
                self._last_best_head = best_text
            
            # INTELLIGENCE: Adaptive Sleep basé sur la vélocité du texte
            now = time.monotonic()
            if self._last_snapshot_ts > 0:
                dt = now - self._last_snapshot_ts
                d_len = final_len - self._last_text_len
                if dt > 0 and d_len > 20: # Texte grandit vite
                    suggested_sleep = 0.05 # Accélération capture
            
            self._last_text_len = final_len
            self._last_snapshot_ts = now
            
            snap_ms = int((time.monotonic() - t_start_snap) * 1000)
            jlog("snapshot_now_result_v7.11", final_len=final_len, head=best_text[:80] if final_len > 0 else "EMPTY", snap_ms=snap_ms, is_json_sentinel=((best_text.endswith("<>") or best_text.endswith("<<END>>")) and best_text.strip().startswith("{")))
            
            # Promotion mini-dump si vide
            if final_len == 0 and GH_DOM_MINIDUMP_ON_EMPTY:
                try:
                    md = await asyncio.wait_for(self.page.evaluate(_MINIDUMP_JS), timeout=2.0)
                    cnt = len(md) if isinstance(md, list) else 0
                    max_show = GH_DOM_MINIDUMP_MAX
                    jlog("dom_mini_dump_candidates_v7.11", count=cnt, heads=(md[:max_show] if isinstance(md, list) else []))
                    if isinstance(md, list) and cnt > 0:
                        best_head = max(md, key=lambda x: (x or {}).get("len", 0))
                        mini_text = (best_head.get("full") or best_head.get("head") or "").strip()
                        if mini_text and len(mini_text) >= 10:
                            best_text = mini_text
                            final_len = len(best_text)
                            # On ne met PAS à jour _last_best_head sur un minidump (trop volatile)
                            jlog("snapshot_now_minidump_promoted_v7.11", new_len=final_len, head=best_text[:80])
                except asyncio.TimeoutError:
                    jlog("dom_mini_dump_timeout_v7.11", level="DEBUG")
                except Exception as dump_err:
                    jlog("dom_mini_dump_error_v7.11", error=str(dump_err), level="DEBUG")

            meta_payload = {
                "ts": time.time(),
                "len": final_len,
                "is_json_sentinel": ((best_text.endswith("<>") or best_text.endswith("<<END>>")) and best_text.strip().startswith("{")),
                "images": getattr(self, '_last_images_seen', []),
                "suggested_next_sleep": suggested_sleep # Feedback pour l'orchestrateur
            }

            return {"text": best_text, "meta": meta_payload}
        
        except Exception as e:
            jlog("dom_snapshot_error", error=str(e), error_type=type(e).__name__)
            return {"text": "", "meta": {"error": str(e), "ts": time.time(), "len": 0, "suggested_next_sleep": 0.5}}