### gemini_headless/collect/producers/dom.py
# CORRIGÉ V25 (FINAL: ANTI-AVATAR DRACONIEN + RATIO PENALTY)
# - _SCAVENGE_IMAGES_JS: Ajout pénalité ratio 1:1 (avatars) et exclusion stricte des URLs de profil.

from __future__ import annotations
import asyncio, time, re, json
from typing import Callable, Optional, List, Dict, Any, Tuple, Set
from playwright.async_api import Page, Frame, Error as PlaywrightError
import os

try:
    from packaging import version
    import playwright
    PW_VERSION = version.parse(playwright.__version__)
    FRAME_EVALUATE_USES_OLD_SIGNATURE = PW_VERSION < version.parse("1.45.0")
except (ImportError, AttributeError, ValueError):
    FRAME_EVALUATE_USES_OLD_SIGNATURE = False

async def safe_frame_evaluate(frame: Frame, script: str, *args) -> Any:
    """Wrapper pour Frame.evaluate() compatible versions."""
    try:
        if FRAME_EVALUATE_USES_OLD_SIGNATURE and len(args) >= 1:
            return await frame.evaluate(script, *args)
        else:
            if len(args) == 1: return await frame.evaluate(script, args[0])
            elif len(args) > 1: return await frame.evaluate(script, args)
            else: return await frame.evaluate(script)
    except TypeError as te:
        try: return await frame.evaluate(script)
        except TypeError:
            jlog("safe_frame_evaluate_crash", error=str(te), level="ERROR")
            raise
    except Exception as e:
        jlog("safe_frame_evaluate_crash", error=str(e), level="ERROR")
        raise

try:
    from ...utils.logs import jlog
except Exception:
    import sys
    def jlog(evt: str, **kw): print(f"JLOG:{evt}:{kw}", file=sys.stderr)

# Runtime toggles
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip().lower()
    return (v in {"1","true","yes","on","y"}) if v else default
def _env_int(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)))
    except: return default

GH_DOM_SCROLL_ENABLE = _env_bool("GH_DOM_SCROLL_ENABLE", True)
GH_DOM_SCROLL_STEPS = _env_int("GH_DOM_SCROLL_STEPS", 6)
GH_DOM_SCROLL_DELAY_MS = _env_int("GH_DOM_SCROLL_DELAY_MS", 120)

GH_DOM_MINIDUMP_ON_EMPTY = _env_bool("GH_DOM_MINIDUMP_ON_EMPTY", True)
GH_DOM_MINIDUMP_MAX = _env_int("GH_DOM_MINIDUMP_MAX", 5)


# --- SCROLLJS Robuste ---
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

                for (let i = 0; i < stepCount; i++) {
                    const prevTop = root.scrollTop;
                    const y = prevTop + (dir === "down" ? scrollDelta : -scrollDelta);
                    root.scrollTo({ top: y, behavior: "instant" });
                    if (delay > 0) await new Promise(r => setTimeout(r, delay));
                    
                    const currentTop = root.scrollTop;
                    const moved = Math.abs(currentTop - prevTop);
                    totalMoved += moved;
                    if (moved < 1) break; 
                }
                return { scrolled: true, delta: totalMoved };
            } catch (innerErr) { return {scrolled: false, error: innerErr.toString()}; }
        });
        const unpack = Array.isArray(args) ? args : (args ? [args] : []);
        return await scrollFunc(unpack[0], unpack[1], unpack[2]);
    } catch (outerErr) { return {scrolled: false, error: outerErr.toString()}; }
}
"""

_MINIDUMP_JS = r"""
() => { try {
    const takeHead = (s, n=200) => (s||"").replace(/\s+/g," ").trim().slice(0,n);
    const sels = ["[data-message-author='assistant']", "article[data-author='assistant']", "[data-message-author]", "article", ".model-response-text"];
    const out = []; const seen = new Set();
    for (const sel of sels) {
      const arr = Array.from(document.querySelectorAll(sel));
      for (let i=arr.length-1;i>=0;i--) {
          const el = arr[i]; if (!el || !el.isConnected || seen.has(el)) continue;
          seen.add(el);
          const txt = (el.innerText || el.textContent || "").trim();
          if (txt && txt.length >= 10) out.push({ len: txt.length, head: takeHead(txt), full: txt });
      }
    }
    out.sort((a,b) => (b.len||0) - (a.len||0));
    return out.slice(0, 5);
} catch(e){ return []; } }
"""

# --- INTELLIGENCE V21 : Snapshot Initial (Pour filtrage différentiel) ---
_SNAPSHOT_EXISTING_IMAGES_JS = r"""
() => {
    try {
        const imgs = Array.from(document.querySelectorAll('img'));
        const sources = imgs.map(i => i.src).filter(s => s && s.length > 5);
        return Array.from(new Set(sources));
    } catch(e) { return []; }
}
"""

# --- INTELLIGENCE N°5 : ACTION DE TÉLÉCHARGEMENT ---
_TRIGGER_DOWNLOAD_JS = r"""
async () => {
    try {
        // Stratégie 1: Bouton Aria-Label précis (Multilingue)
        const labels = [
            'download full size', 'download image', 'télécharger l\'image', 
            'export', 'exporter', 'télécharger', 'download'
        ];
        
        // On cherche d'abord dans les conteneurs d'images récents
        const containers = Array.from(document.querySelectorAll('div[class*="image"], div[class*="media"], model-response-container'));
        let candidates = [];
        
        containers.forEach(c => {
             candidates = candidates.concat(Array.from(c.querySelectorAll('button, a[role="button"], mat-icon')));
        });
        
        // Fallback global
        if (candidates.length === 0) {
            candidates = Array.from(document.querySelectorAll('button, a[role="button"], mat-icon'));
        }

        // Renverser pour prioriser les boutons les plus récents (bas de page)
        candidates.reverse();

        for (const btn of candidates) {
             const label = (btn.getAttribute('aria-label') || "").toLowerCase();
             const tooltip = (btn.getAttribute('data-tooltip') || "").toLowerCase();
             const text = (btn.innerText || "").toLowerCase();
             
             // Vérification par Label
             if (labels.some(l => label.includes(l) || tooltip.includes(l) || (text === l))) {
                 if (btn.offsetParent !== null && !btn.disabled) {
                     btn.scrollIntoView({block: "center"});
                     btn.click();
                     return { triggered: true, method: 'aria_label', label: label || text };
                 }
             }
             
             // Vérification par SVG Path (Icone Download standard Google)
             const svg = btn.querySelector('svg');
             if (svg) {
                 const path = svg.querySelector('path');
                 if (path) {
                     const d = path.getAttribute('d') || "";
                     // Signature approximative d'une flèche vers le bas ou disquette
                     if (d.includes("M19 9h-4V3H9v6H5l7 7 7-7z") || d.length < 100 && (label.includes('load') || label === "")) {
                         if (btn.offsetParent !== null) {
                             btn.click();
                             return { triggered: true, method: 'svg_path' };
                         }
                     }
                 }
             }
        }
        
        // Stratégie 2: Icône Material "download"
        const icons = Array.from(document.querySelectorAll('mat-icon'));
        icons.reverse();
        for (const icon of icons) {
            if (icon.innerText.trim() === 'download' || icon.getAttribute('data-mat-icon-name') === 'download') {
                const parentBtn = icon.closest('button, a');
                if (parentBtn && parentBtn.offsetParent !== null) {
                    parentBtn.click();
                    return { triggered: true, method: 'mat_icon' };
                }
            }
        }
        
        return { triggered: false };
    } catch(e) { return { triggered: false, error: e.toString() }; }
}
"""

# --- INTELLIGENCE V22 : Scavenging + Hystérésis + Smart Thinking + Semantic Validation ---
_GET_BEST_TEXT_JS = r"""
async (args) => {
    try {
        const unpack = Array.isArray(args) ? args : (args ? [args] : []);
        const prevHeadArg = unpack[0] || null;

        const isVisible = (el) => {
            try {
                if (!el || !el.isConnected) return false;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                const s = getComputedStyle(el);
                return !(s.visibility === "hidden" || s.display === "none" || s.opacity === "0");
            } catch (e) { return false; }
        };
        
        const deepTextContent = (el) => {
            try { return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim(); } 
            catch (e) { return ""; }
        };

        const checkGeneratingState = (rootEl) => {
            try {
                const skeletons = document.querySelectorAll('.skeleton-image, [aria-label*="Generating"], mat-spinner, [data-test-id="loading-indicator"]');
                if (skeletons.length > 0) return true;
                
                const placeholders = Array.from(document.querySelectorAll('div[class*="loading"], div[class*="skeleton"]'));
                for (const p of placeholders) {
                    const r = p.getBoundingClientRect();
                    if (r.width > 200 && r.height > 200 && isVisible(p)) return true;
                }

                if (rootEl) {
                    const txt = deepTextContent(rootEl).toLowerCase();
                    if ((txt.includes("creating image") || txt.includes("création de l'image") || txt.includes("generating")) && rootEl.querySelectorAll('img').length === 0) {
                        return true;
                    }
                }
                return false;
            } catch(e) { return false; }
        };

        const extractImages = (rootEl) => {
             const candidates = [];
             if (rootEl) candidates.push(...Array.from(rootEl.querySelectorAll('img')));
             candidates.push(...Array.from(document.querySelectorAll('img[src*="googleusercontent"], img[alt*="Image générée"]')));
             
             const validImgs = [];
             const seenSrc = new Set();
             
             for (const img of candidates) {
                 if (!img.src || seenSrc.has(img.src)) continue;
                 if (img.naturalWidth > 10 && img.naturalWidth < 150) continue; 
                 // --- STRICT FILTERING IN DOM ---
                 if (img.src.includes("profile/picture") || img.src.includes("/a/") || img.alt.includes("Logo") || img.alt.includes("Avatar")) continue;
                 
                 seenSrc.add(img.src);
                 validImgs.push({
                     src: img.src,
                     alt: img.alt || "",
                     width: img.naturalWidth,
                     height: img.naturalHeight,
                     loading: img.loading
                 });
             }
             return validImgs;
        };

        const findContinuationButton = () => {
            const keywords = ['continue', 'continuer', 'show more', 'plus', 'regenerate', 'générer', 'afficher la suite'];
            const buttons = Array.from(document.querySelectorAll('button, div[role="button"], a[role="button"]'));
            for (const btn of buttons) {
                if (!isVisible(btn)) continue;
                const txt = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
                if (keywords.some(k => txt.includes(k))) {
                     let sel = btn.tagName.toLowerCase();
                     if (btn.id) sel += `#${btn.id}`;
                     else if (btn.className) sel += `.${btn.className.split(' ')[0]}`;
                     if (btn.getAttribute('aria-label')) sel += `[aria-label="${btn.getAttribute('aria-label')}"]`;
                     return { selector: sel, text: txt };
                }
            }
            return null;
        };
        
        // --- INTELLIGENCE N°2: Semantic Fragmentation Detection ---
        const checkSemanticIntegrity = (text) => {
            if (!text || text.length < 5) return "too_short";
            
            // Check Start
            const start = text.slice(0, 10).trim();
            const firstChar = start[0];
            const isLower = (firstChar === firstChar.toLowerCase() && firstChar !== firstChar.toUpperCase());
            const isCode = start.startsWith("`") || start.startsWith("{") || start.startsWith("[");
            
            // Si commence par minuscule et pas code, c'est probablement coupé
            if (isLower && !isCode && /[a-z]/.test(firstChar)) return "truncated_start";
            
            return "ok";
        };

        const isThinkingBlock = (el, text) => {
            const cls = (el.className || "").toLowerCase();
            const head = text.slice(0, 100).toLowerCase();
            if (cls.includes("thinking") || cls.includes("thought") || cls.includes("draft") || cls.includes("expandable")) return true;
            if (el.closest('.thinking-container') || el.closest('[data-test-id="thinking-process"]')) return true;
            if (el.getAttribute("data-test-id") === "thinking-process") return true;
            if (head.startsWith("analyzing") || head.includes("i need to") || head.includes("user wants")) return true;
            if (head.includes("analyzing the question") || head.includes("step 1")) return true;
            if (head.includes("thinking process") || head.includes("thought process")) return true;
            return false;
        };

        // --- INTELLIGENCE N°3: Selector Persistence (Memory) ---
        if (!window._gemini_selector_scores) window._gemini_selector_scores = {}; 
        
        const BASE_SELS = [
            "[data-message-author='assistant']:not([aria-busy='true']) .model-response-text",
            "[data-message-author='assistant']",
            "article", ".model-response-text", ".response-content-container", "main [role='feed'] article"
        ];
        
        const SORTED_SELS = [...BASE_SELS].sort((a,b) => (window._gemini_selector_scores[b] || 0) - (window._gemini_selector_scores[a] || 0));
        const ALL_SELS = SORTED_SELS.join(',');
        
        const zones = Array.from(document.querySelectorAll('main, [role="main"], [aria-live], body')) || [document.body];
        let best = null, bestScore = -1000, bestSelectorUsed = null;
        let thinkingFound = false;

        for (const zone of zones) {
             if (!zone || !zone.isConnected) continue;
             const cands = Array.from(zone.querySelectorAll(ALL_SELS));
             if (zone.matches('div, section, article') && isVisible(zone)) cands.push(zone);

             for (const n of cands) {
                 if (!n || !n.isConnected) continue;
                 const txt = deepTextContent(n);
                 const len = txt.length;
                 if (len == 0 && !isVisible(n)) continue;

                 const isThinking = isThinkingBlock(n, txt);
                 if (isThinking) thinkingFound = true;

                 let score = 0;
                 if (isThinking) score -= 5000; 
                 if (len > 50) score += 20 + Math.min(len / 50, 20);
                 const cls = (n.className || "").toLowerCase();
                 if (cls.includes("response") || cls.includes("message-content")) score += 50;
                 if (prevHeadArg && txt.startsWith(prevHeadArg) && score > -100) score += 50;

                 if (score > bestScore) { 
                     bestScore = score; best = n; 
                     for(const s of BASE_SELS) if (n.matches(s)) { bestSelectorUsed = s; break; }
                 }
             }
        }

        if (!best) {
             const found = document.querySelector(".model-response-text");
             if(found && isVisible(found)) { best = found; bestSelectorUsed = ".model-response-text"; }
        }

        if (bestSelectorUsed && window._gemini_selector_scores && bestScore > 0) {
             window._gemini_selector_scores[bestSelectorUsed] = (window._gemini_selector_scores[bestSelectorUsed] || 0) + 1;
        }

        const continuation = findContinuationButton();
        let finalTxt = best ? deepTextContent(best) : "";
        let is_thinking_state = false;
        
        const imagesFound = extractImages(best);
        const isGeneratingMedia = checkGeneratingState(best);

        if (best && isThinkingBlock(best, finalTxt)) {
            is_thinking_state = true;
        } else if (thinkingFound && finalTxt.length < 50) {
            is_thinking_state = true;
        }

        const integrity = checkSemanticIntegrity(finalTxt);

        return {
            text: finalTxt,
            images: imagesFound, 
            continuation: continuation,
            is_truncated_head: (integrity === "truncated_start"),
            is_thinking_state: is_thinking_state,
            score: bestScore,
            dom_status: isGeneratingMedia ? "generating_media" : "normal"
        };

    } catch(e) { return {text: "", images: [], error: e.toString()}; }
}
"""

# --- FILTRAGE INTELLIGENT V25 (HEURISTIQUE SPATIALE + ANTI-AVATAR DRACONIEN) ---
_SCAVENGE_IMAGES_JS = r"""
async (args) => {
    try {
        const unpack = Array.isArray(args) ? args : (args ? [args] : []);
        const existingImages = new Set(unpack[0] || []); 
        
        const found = [];
        const seen = new Set();
        
        const imgs = Array.from(document.querySelectorAll('img'));
        const blacklistSelectors = ['header', 'nav', '.sidebar', '[role="banner"]'];
        const blacklistElements = new Set();
        blacklistSelectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => blacklistElements.add(el));
        });

        // Fonction de Scoring Structurel
        const calculateImageConfidence = (img) => {
            let score = 0;
            const w = img.naturalWidth;
            const h = img.naturalHeight;

            // 1. Critère de Taille
            if (w > 300 && h > 300) score += 20;
            if (w > 800) score += 10;

            // 2. Critère de Voisinage (Indices d'interface)
            const container = img.closest('div, article, figure'); 
            if (container) {
                const html = container.innerHTML.toLowerCase();
                const text = container.innerText.toLowerCase();
                
                // Boutons d'action typiques d'une génération
                if (html.includes('download') || html.includes('télécharger')) score += 30;
                if (html.includes('share') || html.includes('partager')) score += 20;
                if (html.includes('agrandir') || html.includes('expand')) score += 20;
                
                // Mots clés de confirmation
                if (text.includes('générée') || text.includes('generated')) score += 20;
            }

            // 3. Critère de Positionnement (Centrage)
            const rect = img.getBoundingClientRect();
            const viewW = window.innerWidth;
            const centerX = rect.left + (rect.width / 2);
            const distFromCenter = Math.abs(centerX - (viewW / 2));
            if (distFromCenter < (viewW * 0.25)) score += 15;

            // 4. Pénalités Draconiennes (ANTI-AVATAR)
            const src = (img.src || "").toLowerCase();
            const alt = (img.alt || "").toLowerCase();
            
            // a) Patterns URL
            if (src.includes('profile')) score -= 500;
            if (src.includes('/a/') && src.includes('googleusercontent')) score -= 500;
            
            // b) Métadonnées
            if (alt.includes('avatar') || alt.includes('profil')) score -= 500;
            
            // c) Ratio Carré Suspect (Typique des avatars affichés en HD)
            // Si l'image est parfaitement carrée et inférieure à 800px, c'est très probablement un avatar.
            if (w === h && w < 800) {
                 score -= 150; 
            }

            return score;
        };

        for (const img of imgs) {
            const src = (img.src || "").toLowerCase();
            
            // FILTRE 0 : Snapshot Différentiel
            if (existingImages.has(img.src)) continue;

            // FILTRE 1 : Taille minimale
            if (img.naturalWidth < 200 || img.naturalHeight < 200) continue;
            
            // FILTRE 2 : Exclusion Systématique (Redondance de sécurité)
            if (src.includes("profile/picture") || src.includes("googleusercontent.com/a/")) continue; 
            if (src.includes("logo") || (img.alt && img.alt.toLowerCase().includes("logo"))) continue; 
            
            // FILTRE 3 : Zone Interdite
            let isInBlacklist = false;
            let p = img.parentElement;
            while(p) {
                if (blacklistElements.has(p)) { isInBlacklist = true; break; }
                p = p.parentElement;
            }
            if (isInBlacklist) continue;

            if (!src || src.startsWith("data:image/gif;base64")) continue; 
            if (seen.has(src)) continue;
            
            // --- INTELLIGENCE N°1: Application du Score ---
            const confidence = calculateImageConfidence(img);
            if (confidence < 20) continue; // Seuil de confiance

            // Force Scroll Into View
            img.scrollIntoView({block: 'center', behavior: 'instant'});
            await new Promise(r => setTimeout(r, 50));
            
            if (img.complete) {
                 seen.add(src);
                 found.push({
                     src: img.src,
                     alt: img.alt || "scavenged_image",
                     width: img.naturalWidth,
                     height: img.naturalHeight,
                     confidence: confidence
                 });
            }
        }
        return found;
    } catch (e) { return []; }
}
"""

class DOMProducer:
    """Producteur DOM (V25 - Snapshot Aware + Auto-Repair + Structural Validation + Download Action)."""

    def __init__(self, page: Page, on_progress: Callable[[str], None], on_done: Callable[[str, Optional[str]], None]):
        self.page = page
        self.on_progress_cb = on_progress
        self.on_done_cb = on_done
        self.done: bool = False
        self._last_best_head: Optional[str] = None
        self._last_text_len = 0
        self._last_snapshot_ts = 0.0
        self._stitch_performed = False

    async def start(self) -> None:
        if self.page.is_closed(): return
        try: await asyncio.wait_for(self.page.evaluate("() => 1+1"), timeout=1.2)
        except: pass

    async def stop(self) -> None:
        self.done = True
        self._last_best_head = None
        self._last_text_len = 0
        self._stitch_performed = False

    async def snapshot_existing_images(self) -> List[str]:
        """Capture l'état visuel actuel pour le filtrage différentiel."""
        try:
            res = await safe_frame_evaluate(self.page.main_frame, _SNAPSHOT_EXISTING_IMAGES_JS)
            return res if isinstance(res, list) else []
        except Exception as e:
            jlog("dom_snapshot_existing_failed", error=str(e))
            return []

    async def _wait_for_dom_stabilization(self, timeout: float = 2.0) -> None:
        try:
            start = time.monotonic()
            last_height = 0
            stable_checks = 0
            while time.monotonic() - start < timeout:
                h = await self.page.evaluate("document.body.scrollHeight")
                if h != last_height:
                    last_height = h
                    stable_checks = 0
                    await asyncio.sleep(0.2)
                else:
                    stable_checks += 1
                    if stable_checks >= 2: break
                    await asyncio.sleep(0.2)
        except: pass

    async def _perform_stitch_recovery(self) -> str:
        jlog("dom_stitch_recovery_started", msg="Détection de texte tronqué.")
        try:
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self._wait_for_dom_stabilization(timeout=2.5)
            res_top = await safe_frame_evaluate(self.page.main_frame, _GET_BEST_TEXT_JS, [None])
            top_text = res_top.get("text", "") if isinstance(res_top, dict) else ""
            
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._wait_for_dom_stabilization(timeout=2.0)
            res_bot = await safe_frame_evaluate(self.page.main_frame, _GET_BEST_TEXT_JS, [top_text[:50]])
            bot_text = res_bot.get("text", "") if isinstance(res_bot, dict) else ""
            
            if len(top_text) > len(bot_text) + 100: return top_text
            elif bot_text.startswith(top_text[:50]): return bot_text
            else:
                 if top_text.strip().startswith("{") and not bot_text.strip().startswith("{"): return top_text 
                 return bot_text
        except Exception as e:
            jlog("dom_stitch_error", error=str(e))
            return ""

    async def snapshot_now(self) -> dict:
        best_text = ""
        found_images = []
        continuation_info = None
        is_thinking_state = False
        dom_status = "normal"
        suggested_sleep = 0.1 

        try:
            if self.page.is_closed(): raise PlaywrightError("Page closed")
            
            if GH_DOM_SCROLL_ENABLE:
                try:
                    await asyncio.wait_for(
                        safe_frame_evaluate(self.page.main_frame, _SCROLL_JS, ["down", GH_DOM_SCROLL_STEPS, GH_DOM_SCROLL_DELAY_MS]),
                        timeout=4.5
                    )
                    await asyncio.sleep(0.05)
                except: pass

            try:
                prev_head_arg = self._last_best_head[:50] if self._last_best_head else None
                result_data = await asyncio.wait_for(
                    safe_frame_evaluate(self.page.main_frame, _GET_BEST_TEXT_JS, [prev_head_arg]), 
                    timeout=5.0 
                )
                
                if isinstance(result_data, str): result_data = {"text": result_data}
                
                best_text = result_data.get("text", "")
                found_images = result_data.get("images", [])
                continuation_info = result_data.get("continuation") 
                is_truncated = result_data.get("is_truncated_head", False)
                is_thinking_state = result_data.get("is_thinking_state", False)
                dom_status = result_data.get("dom_status", "normal")

                if is_truncated and not self._stitch_performed and len(best_text) > 20:
                    stitched = await self._perform_stitch_recovery()
                    if len(stitched) > len(best_text):
                        best_text = stitched
                    self._stitch_performed = True

            except Exception: pass

            final_len = len(best_text)
            if final_len > 10: self._last_best_head = best_text
            
            now = time.monotonic()
            if self._last_snapshot_ts > 0:
                d_len = final_len - self._last_text_len
                if d_len > 20: suggested_sleep = 0.05
            self._last_text_len = final_len
            self._last_snapshot_ts = now
            
            if final_len == 0 and GH_DOM_MINIDUMP_ON_EMPTY:
                try:
                    md = await asyncio.wait_for(self.page.evaluate(_MINIDUMP_JS), timeout=2.0)
                    if isinstance(md, list) and md:
                        best = max(md, key=lambda x: x.get("len", 0))
                        best_text = best.get("full", "") or best.get("head", "")
                        final_len = len(best_text)
                except: pass

            meta_payload = {
                "ts": time.time(),
                "len": final_len,
                "is_json_sentinel": ((best_text.endswith("<>") or best_text.endswith("<<END>>")) and best_text.strip().startswith("{")),
                "suggested_next_sleep": suggested_sleep,
                "continuation_candidate": continuation_info,
                "dom_score": result_data.get("score", 0) if isinstance(result_data, dict) else 0,
                "is_thinking_state": is_thinking_state,
                "dom_status": dom_status
            }
            
            return {"text": best_text, "images": found_images, "meta": meta_payload}
        
        except Exception as e:
            jlog("dom_snapshot_error", error=str(e))
            return {"text": "", "images": [], "meta": {"error": str(e), "ts": time.time(), "len": 0}}

    async def scavenge_images(self, existing_images_blacklist: List[str] = None) -> List[Dict]:
        """
        Méthode Intelligence V25 : Scavenging Différentiel & Structurel.
        Accepte une liste noire d'URLs (snapshot) pour éliminer les faux positifs.
        """
        jlog("dom_scavenge_hunt_start", blacklist_size=len(existing_images_blacklist or []))
        try:
            args = [existing_images_blacklist or []]
            images = await safe_frame_evaluate(self.page.main_frame, _SCAVENGE_IMAGES_JS, args)
            return images if isinstance(images, list) else []
        except Exception as e:
            jlog("dom_scavenge_hunt_error", error=str(e))
            return []

    async def trigger_download_action(self) -> Dict[str, Any]:
        """Tentative d'action explicite de téléchargement via le DOM."""
        try:
            res = await safe_frame_evaluate(self.page.main_frame, _TRIGGER_DOWNLOAD_JS)
            if res.get("triggered"):
                jlog("dom_trigger_download_success", method=res.get("method"), label=res.get("label"))
            return res
        except Exception as e:
            jlog("dom_trigger_download_failed", error=str(e))
            return {"triggered": False, "error": str(e)}