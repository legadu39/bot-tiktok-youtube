"""
UI interaction utilities for input and submission with Adaptive Intelligence
Updates V32: Added Time Decay for selectors & Structural Signature Validation.
             Added Session Fast-Fail for selectors (Intelligence N°4).
             FIX: Utilisation de Shift+Enter pour les retours à la ligne.
"""

import asyncio
import time
import json
import math
from pathlib import Path
from typing import Optional, Tuple, List, Dict, ClassVar, Any

from playwright.async_api import (
    Page,
    ElementHandle,
    TimeoutError as PWTimeout,
    Error as PlaywrightError
)

from .config import Config, Selectors
from .logger import logger
from .cache import SelectorCache


class InputHandler:
    """Handles input field interactions with probabilistic selector ranking, PID typing, and Predictive Cache."""
    
    # Structure v2: {selector: {"score": int, "last_used": float}}
    # Supporte la retro-compatibilité avec v1 {selector: int}
    _selector_scores: ClassVar[Dict[str, Any]] = {}
    _scores_file: ClassVar[Path] = Path("selector_scores.json")
    
    _clear_prefs: ClassVar[Dict[str, str]] = {}
    _clear_prefs_file: ClassVar[Path] = Path("clear_prefs.json")
    
    # Intelligence: Cache des Signatures de Page (Hash -> Selector)
    _page_signatures: ClassVar[Dict[str, str]] = {}
    _signatures_file: ClassVar[Path] = Path("page_signatures.json")
    
    _loaded: ClassVar[bool] = False

    # Intelligence N°4: Mémoire de session pour le "Fast Fail"
    def __init__(self, cache: Optional[SelectorCache] = None):
        self.cache = cache or SelectorCache()
        self._session_failures: Dict[str, int] = {} 
        if not InputHandler._loaded:
            self._load_persistent_scores()
            InputHandler._loaded = True
    
    @classmethod
    def _apply_time_decay(cls):
        """Applique une dépréciation aux scores basés sur le temps écoulé."""
        now = time.time()
        decay_factor_per_day = 0.90 # -10% par jour
        
        for sel, data in cls._selector_scores.items():
            if isinstance(data, dict):
                last_used = data.get("last_used", now)
                score = data.get("score", 0)
                
                days_passed = (now - last_used) / 86400.0
                if days_passed > 1:
                    new_score = score * (decay_factor_per_day ** days_passed)
                    if new_score < -5: new_score = -5
                    cls._selector_scores[sel]["score"] = int(new_score)
                    logger.debug("selector_score_decayed", selector=sel, old=score, new=int(new_score), days=f"{days_passed:.1f}")

    @classmethod
    def _load_persistent_scores(cls):
        try:
            if cls._scores_file.exists():
                with open(cls._scores_file, "r", encoding="utf-8") as f:
                    saved_data = json.load(f)
                    
                    migrated_data = {}
                    for k, v in saved_data.items():
                        if isinstance(v, int) or isinstance(v, float):
                            migrated_data[k] = {"score": int(v), "last_used": time.time()}
                        else:
                            migrated_data[k] = v
                    
                    cls._selector_scores.update(migrated_data)
                    
                cls._apply_time_decay()
            
            if cls._clear_prefs_file.exists():
                with open(cls._clear_prefs_file, "r", encoding="utf-8") as f:
                    saved_prefs = json.load(f)
                    cls._clear_prefs.update(saved_prefs)
            
            if cls._signatures_file.exists():
                with open(cls._signatures_file, "r", encoding="utf-8") as f:
                    saved_sigs = json.load(f)
                    cls._page_signatures.update(saved_sigs)

            logger.info("input_handler_loaded", 
                        scores=len(cls._selector_scores), 
                        prefs=len(cls._clear_prefs),
                        signatures=len(cls._page_signatures))
        except Exception as e:
            logger.warn("selector_scores_load_failed", error=str(e))

    def _save_persistent_scores(self):
        try:
            with open(self._scores_file, "w", encoding="utf-8") as f:
                json.dump(self._selector_scores, f, indent=2)
            
            with open(self._clear_prefs_file, "w", encoding="utf-8") as f:
                json.dump(self._clear_prefs, f, indent=2)
            
            with open(self._signatures_file, "w", encoding="utf-8") as f:
                json.dump(self._page_signatures, f, indent=2)
        except Exception as e:
            logger.debug("selector_scores_save_failed", error=str(e))

    def _get_score(self, selector: str) -> int:
        entry = self._selector_scores.get(selector, {"score": 0})
        if isinstance(entry, int): return entry
        return entry.get("score", 0)

    def _get_sorted_selectors(self, base_selectors: List[str]) -> List[str]:
        return sorted(
            base_selectors,
            key=lambda s: self._get_score(s),
            reverse=True
        )

    def _update_score(self, selector: str, success: bool):
        current_entry = self._selector_scores.get(selector, {"score": 0, "last_used": time.time()})
        current_score = current_entry.get("score", 0)
        
        if success:
            new_score = min(current_score + 1, 30)
        else:
            new_score = max(current_score - 5, -15)
            
        self._selector_scores[selector] = {
            "score": new_score,
            "last_used": time.time()
        }
        self._save_persistent_scores()
    
    def _update_clear_pref(self, selector: str, method: str):
        if selector and method:
            self._clear_prefs[selector] = method
            self._save_persistent_scores()

    async def _get_page_signature(self, page: Page) -> str:
        try:
            return await page.evaluate("""() => {
                const divs = document.querySelectorAll('div').length;
                const inputs = document.querySelectorAll('input, textarea, [contenteditable="true"]').length;
                const buttons = document.querySelectorAll('button, [role="button"]').length;
                const len = Math.floor(document.body.innerText.length / 500); 
                return `sig_v2_${divs}_${inputs}_${buttons}_${len}`;
            }""")
        except: return "unknown"

    async def _locate_heuristic(self, page: Page) -> Tuple[Optional[ElementHandle], Optional[str]]:
        try:
            heuristic_js = """
            () => {
                const candidates = [];
                const nodes = document.querySelectorAll('div[contenteditable="true"], textarea, input[type="text"]');
                
                nodes.forEach(node => {
                    if (node.offsetParent === null) return; 
                    
                    let score = 0;
                    const style = window.getComputedStyle(node);
                    if (style.visibility === 'hidden' || style.display === 'none') return;
                    
                    if (node.getAttribute('contenteditable') === 'true') score += 10;
                    if (node.tagName === 'TEXTAREA') score += 5;
                    if (node.getAttribute('aria-label')) score += 5;
                    if (node.getAttribute('placeholder')) score += 3;
                    
                    const rect = node.getBoundingClientRect();
                    if (rect.width > 200) score += 5; 
                    if (rect.height > 20) score += 2;
                    
                    const outer = node.outerHTML.toLowerCase();
                    if (outer.includes('prompt') || outer.includes('ask') || outer.includes('gemini')) score += 10;

                    candidates.push({node: node, score: score});
                });
                
                candidates.sort((a, b) => b.score - a.score);
                
                if (candidates.length > 0) {
                    const best = candidates[0].node;
                    let path = best.tagName.toLowerCase();
                    if (best.id) {
                        path += `#${best.id}`;
                    } else if (best.className) {
                        path += `.${best.className.split(' ').join('.')}`;
                    }
                    if (best.getAttribute('aria-label')) {
                        path += `[aria-label="${best.getAttribute('aria-label')}"]`;
                    }
                    if (path.indexOf('[') === -1 && path.indexOf('#') === -1 && path.indexOf('.') === -1) {
                         if (best.getAttribute('role')) path += `[role="${best.getAttribute('role')}"]`;
                    }
                    
                    return path;
                }
                return null;
            }
            """
            best_selector = await page.evaluate(heuristic_js)
            if best_selector:
                logger.info("input_located_via_heuristic", selector=best_selector)
                element = await page.query_selector(best_selector)
                return element, best_selector
            
            return None, None
        except Exception as e:
            logger.warn("heuristic_location_failed", error=str(e))
            return None, None

    async def locate_input_field(
        self,
        page: Page,
        timeout_ms: int = Config.GH_LOCATE_FILL_TIMEOUT_MS,
        use_cache: bool = True,
        extra_selectors: Optional[List[str]] = None
    ) -> Tuple[Optional[ElementHandle], Optional[str]]:
        try:
            url = page.url
            current_sig = await self._get_page_signature(page)
            
            if use_cache and current_sig in self._page_signatures:
                sig_selector = self._page_signatures[current_sig]
                if self._session_failures.get(sig_selector, 0) <= 2:
                    try:
                        element = await page.query_selector(sig_selector)
                        if element and await element.is_visible():
                            logger.info("input_located_via_fingerprint", signature=current_sig, selector=sig_selector)
                            self._update_score(sig_selector, True)
                            return element, sig_selector
                        else:
                            logger.warn("fingerprint_mismatch_element_gone", signature=current_sig)
                            del self._page_signatures[current_sig]
                            self._session_failures[sig_selector] = self._session_failures.get(sig_selector, 0) + 1
                    except Exception: 
                        self._session_failures[sig_selector] = self._session_failures.get(sig_selector, 0) + 1
                        pass

            if use_cache:
                try:
                    cached_selector = self.cache.get(url)
                    if cached_selector and cached_selector != self._page_signatures.get(current_sig):
                         if self._session_failures.get(cached_selector, 0) <= 2:
                            element = await page.query_selector(cached_selector)
                            if element and await element.is_visible():
                                logger.info("input_located_from_url_cache", selector=cached_selector)
                                self._update_score(cached_selector, True)
                                self._page_signatures[current_sig] = cached_selector
                                self._save_persistent_scores()
                                return element, cached_selector
                except Exception: pass
            
            candidates = list(Selectors.INPUT_SELECTORS)
            if extra_selectors:
                candidates = [s for s in extra_selectors if s not in candidates] + candidates
            
            viable_candidates = [s for s in candidates if self._get_score(s) > -10]
            if not viable_candidates: viable_candidates = candidates
                
            sorted_candidates = self._get_sorted_selectors(viable_candidates)
            t_start = time.monotonic()
            
            for selector in sorted_candidates:
                if (time.monotonic() - t_start) * 1000 > timeout_ms: break
                if self._session_failures.get(selector, 0) > 2: continue

                try:
                    score = self._get_score(selector)
                    step_timeout = 200 if score < 0 else 500
                    
                    element = await page.wait_for_selector(
                        selector,
                        state="visible",
                        timeout=min(step_timeout, timeout_ms)
                    )
                    
                    if element:
                        logger.info("input_located_via_scan", selector=selector, score=score)
                        self._update_score(selector, True)
                        if use_cache:
                            self.cache.set(url, selector)
                            self._page_signatures[current_sig] = selector 
                            self._save_persistent_scores()
                        return element, selector
                        
                except PWTimeout:
                    self._update_score(selector, False)
                    self._session_failures[selector] = self._session_failures.get(selector, 0) + 1
                    continue
                except Exception:
                    self._session_failures[selector] = self._session_failures.get(selector, 0) + 1
                    continue
            
            logger.info("input_not_found_standard_strategy", tried=len(sorted_candidates))
            element, heuristic_selector = await self._locate_heuristic(page)
            if element:
                if use_cache:
                     self._page_signatures[current_sig] = heuristic_selector 
                     self._save_persistent_scores()
                return element, heuristic_selector

            logger.error("input_not_found_all_strategies")
            return None, None
            
        except Exception as e:
            logger.error("locate_input_error", error=str(e))
            return None, None
    
    async def clear_input(
        self,
        page: Page,
        element: Optional[ElementHandle] = None,
        selector: Optional[str] = None
    ) -> bool:
        try:
            if not element and selector:
                element = await page.query_selector(selector)
            
            if not element:
                return False
            
            preferred = self._clear_prefs.get(selector, "triple_click") if selector else "triple_click"
            
            async def do_triple_click():
                await element.click(click_count=3)
                await page.keyboard.press("Delete")
                return "triple_click"

            async def do_select_all():
                await element.focus()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Delete")
                return "select_all"

            async def do_js_clear():
                await page.evaluate("""
                    (element) => {
                        if (element.value !== undefined) {
                            element.value = '';
                        } else if (element.innerText !== undefined) {
                            element.innerText = '';
                        }
                        element.dispatchEvent(new Event('input', {bubbles: true}));
                        element.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                """, element)
                return "js_clear"

            strategies = []
            if preferred == "triple_click":
                strategies = [do_triple_click, do_select_all, do_js_clear]
            elif preferred == "select_all":
                strategies = [do_select_all, do_triple_click, do_js_clear]
            else:
                strategies = [do_js_clear, do_triple_click, do_select_all]

            for strategy in strategies:
                try:
                    method_name = await strategy()
                    val = await element.input_value()
                    if not val or val.strip() == "":
                        logger.debug(f"clear_input_success", method=method_name)
                        if selector and method_name != preferred:
                             self._update_clear_pref(selector, method_name)
                        return True
                except Exception:
                    continue
            
            return True
            
        except Exception as e:
            logger.error("clear_input_error", error=str(e))
            return False

    async def _type_via_js_injection(self, page: Page, text: str, element: ElementHandle):
        """Fallback method using JS Injection."""
        try:
            await page.evaluate("""(data) => {
                const { text, element } = data;
                try {
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const event = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
                    element.dispatchEvent(event);
                } catch (e) { }
                
                if (element.value !== undefined) {
                    if (element.value === '') element.value = text;
                } else if (element.isContentEditable) {
                     if (element.innerText === '' || element.innerText === '\\n') element.innerText = text;
                }
                
                element.dispatchEvent(new Event('input', {bubbles: true}));
                element.dispatchEvent(new Event('change', {bubbles: true}));
            }""", {"text": text, "element": element})
            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logger.warn("js_injection_failed", error=str(e))
            return False

    async def type_text(
        self,
        page: Page,
        text: str,
        element: Optional[ElementHandle] = None,
        selector: Optional[str] = None,
        delay_ms: int = 50
    ) -> bool:
        """
        Type text using PID Controller Logic and safe newlines (Shift+Enter).
        """
        try:
            if not element and selector:
                element = await page.query_selector(selector)
            
            if not element:
                logger.error("type_text_no_element")
                return False
            
            await element.focus()
            
            t_probe = time.perf_counter()
            try:
                await page.evaluate("1+1")
                probe_latency = (time.perf_counter() - t_probe) * 1000
            except Exception:
                probe_latency = 9999
            
            complexity_score = len(text) + (text.count('\n') * 20)
            
            if probe_latency > 100 or complexity_score > 2000:
                logger.info("typing_strategy_lag_detected_fast_mode", latency=f"{probe_latency:.1f}ms", complexity=complexity_score)
                return await self._type_via_js_injection(page, text, element)

            logger.info("typing_strategy_pid_mode", length=len(text), start_latency=f"{probe_latency:.1f}ms")
            
            target_latency = 50.0  
            current_delay = float(delay_ms)
            
            # --- FIX: Split text by newline to use Shift+Enter ---
            lines = text.split('\n')
            
            for line_idx, line in enumerate(lines):
                if line:
                    chunk_size = 50 
                    chunks = [line[i:i+chunk_size] for i in range(0, len(line), chunk_size)]
                    
                    for i, chunk in enumerate(chunks):
                        await page.keyboard.type(chunk, delay=int(current_delay))
                        
                        if i < len(chunks) - 1: 
                            m_start = time.perf_counter()
                            try:
                                await page.evaluate("1") 
                                actual_latency = (time.perf_counter() - m_start) * 1000
                                
                                if actual_latency > 300:
                                    logger.warn("pid_latency_critical_switch_to_js", latency=f"{actual_latency:.1f}ms")
                                    # Calcul du texte restant en préservant les retours à la ligne
                                    remaining_chunks = "".join(chunks[i+1:])
                                    remaining_lines = "\n".join(lines[line_idx+1:])
                                    remaining_text = remaining_chunks
                                    if line_idx < len(lines) - 1:
                                        remaining_text += "\n" + remaining_lines
                                        
                                    return await self._type_via_js_injection(page, remaining_text, element)
                                
                                error = actual_latency - target_latency
                                correction = error * 0.5 
                                current_delay += correction
                                current_delay = max(5.0, min(current_delay, 150.0))
                                
                            except Exception:
                                current_delay += 20
                
                # --- FIX: Shift+Enter pour sauter une ligne sans envoyer ---
                if line_idx < len(lines) - 1:
                    await page.keyboard.press("Shift+Enter")
                    await asyncio.sleep(0.05) # Laisse le temps au DOM de réagir
            
            return True
            
        except Exception as e:
            logger.error("type_text_error", error=str(e))
            return False


class SubmitHandler:
    """Handles form submission with persistent strategy"""
    
    _preferred_method: ClassVar[str] = "enter"
    
    @classmethod
    async def smart_submit(
        cls,
        page: Page,
        timeout_ms: int = Config.GH_SUBMIT_BUTTON_CLICK_TIMEOUT_MS
    ) -> Tuple[bool, str]:
        methods = ["enter", "click"]
        if cls._preferred_method == "click":
            methods = ["click", "enter"]
        
        last_error = None
        for method in methods:
            try:
                success = False
                desc = ""
                
                if method == "enter":
                    success, desc = await cls.submit_by_enter_key(page)
                else:
                    success, desc = await cls.submit_by_button_click(page, timeout_ms)
                
                if success:
                    if cls._preferred_method != method:
                        logger.info("submit_strategy_changed", old=cls._preferred_method, new=method)
                        cls._preferred_method = method
                    return True, desc
                    
            except Exception as e:
                last_error = e
                logger.warn("submit_method_failed", method=method, error=str(e))
                continue
        
        return False, f"all_methods_failed_last_{str(last_error)[:30]}"

    @staticmethod
    async def submit_by_button_click(
        page: Page,
        timeout_ms: int = Config.GH_SUBMIT_BUTTON_CLICK_TIMEOUT_MS
    ) -> Tuple[bool, str]:
        try:
            js_click_script = f"""
                async () => {{
                    const selectors = {Selectors.SUBMIT_BUTTON_SELECTORS};
                    for (const selector of selectors) {{
                        const buttons = document.querySelectorAll(selector);
                        for (const button of buttons) {{
                            if (button && !button.disabled && button.offsetParent !== null) {{
                                button.click();
                                button.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                                button.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
                                button.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
                                return {{ success: true, selector: selector, method: 'javascript_click' }};
                            }}
                        }}
                    }}
                    return {{ success: false }};
                }}
            """
            result = await page.evaluate(js_click_script)
            if result["success"]:
                logger.info("submit_button_clicked", method="javascript", selector=result.get("selector"))
                return True, f"JS_click_{result.get('selector', 'unknown')[:30]}"
            
            selector_string = Selectors.get_submit_button_selector_string()
            try:
                button = page.locator(selector_string).first
                await button.wait_for(state="visible", timeout=min(1000, timeout_ms))
                await button.click(timeout=min(2000, timeout_ms), force=True)
                return True, "playwright_click"
            except PWTimeout:
                return False, "button_not_found"
        except Exception as e:
            logger.error("submit_button_error", error=str(e))
            return False, f"error_{str(e)[:50]}"
    
    @staticmethod
    async def submit_by_enter_key(page: Page) -> Tuple[bool, str]:
        try:
            await page.keyboard.press("Enter")
            logger.info("submit_by_enter_dispatched")
            return True, "enter_key"
        except Exception as e:
            logger.error("submit_enter_error", error=str(e))
            return False, f"enter_error_{str(e)[:50]}"
    
    @staticmethod
    async def test_button_responsive(page: Page, timeout_ms: int = 600) -> bool:
        try:
            test_script = f"""
                async () => {{
                    const selectors = {Selectors.SUBMIT_BUTTON_SELECTORS};
                    for (const selector of selectors) {{
                        const button = document.querySelector(selector);
                        if (button && !button.disabled) {{
                            const style = window.getComputedStyle(button);
                            if (style.pointerEvents === 'none' ||
                                style.visibility === 'hidden' ||
                                style.display === 'none') {{
                                continue;
                            }}
                            return true;
                        }}
                    }}
                    return false;
                }}
            """
            return await page.evaluate(test_script)
        except Exception:
            return False


class UploadHandler:
    """Handles file upload operations"""
    
    @staticmethod
    async def upload_files(
        page: Page,
        file_paths: List[str],
        timeout_ms: int = Config.UPLOAD_TIMEOUT_MS
    ) -> bool:
        try:
            logger.info("upload_files_start", count=len(file_paths))
            file_input_selectors = [
                'input[type="file"]',
                'input[accept*="image"]',
                'input[accept*="video"]',
                'input[accept*="*"]'
            ]
            file_input = None
            for selector in file_input_selectors:
                try:
                    file_input = await page.wait_for_selector(
                        selector,
                        timeout=min(2000, timeout_ms),
                        state="attached"
                    )
                    if file_input:
                        break
                except PWTimeout:
                    continue
            
            if not file_input:
                logger.error("file_input_not_found")
                return False
            
            await file_input.set_input_files(file_paths)
            logger.info("files_set_to_input", count=len(file_paths))
            await asyncio.sleep(1)
            return True
        except Exception as e:
            logger.error("upload_files_error", error=str(e))
            return False
    
    @staticmethod
    async def detect_upload_complete(
        page: Page,
        timeout_ms: int = Config.UPLOAD_TIMEOUT_MS
    ) -> bool:
        try:
            from .timing import TimingUtils
            return await TimingUtils.wait_for_upload_complete(page, timeout_ms)
        except Exception as e:
            logger.error("detect_upload_error", error=str(e))
            return False


class RecoveryHandler:
    """
    Handles autonomous recovery actions (Self-Healing).
    """
    
    @staticmethod
    async def attempt_generic_retry(page: Page) -> bool:
        try:
            retry_selectors = [
                "button[aria-label*='Regenerate']",
                "button[aria-label*='Retry']",
                "button[aria-label*='Ressayer']",
                "button:has-text('Regenerate')",
                "button:has-text('Retry')",
                "button:has-text('Réessayer')",
                ".regenerate-response-button"
            ]
            
            js_retry_script = """
            () => {
                const selectors = arguments[0];
                for (const sel of selectors) {
                    const btn = document.querySelector(sel);
                    if (btn && btn.offsetParent !== null && !btn.disabled) {
                        btn.click();
                        return { clicked: true, selector: sel };
                    }
                }
                return { clicked: false };
            }
            """
            
            for selector in retry_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn and await btn.is_visible() and await btn.is_enabled():
                        logger.info("recovery_action_triggered", action="click_retry", selector=selector)
                        await btn.click()
                        return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            logger.warn("recovery_attempt_failed", error=str(e))
            return False


class DownloadHandler:
    """
    Handles file download interactions (Playwright-native strategy + Fallback).
    Provides a robust alternative to JS injection for clicking download buttons.
    """

    @staticmethod
    async def click_download_button(page: Page, timeout_ms: int = 5000) -> bool:
        try:
            last_response = page.locator("model-response-container, article, .model-response-text").last
            
            selectors = [
                "button[aria-label*='Download']", 
                "button[aria-label*='Télécharger']",
                "button[aria-label*='Export']",
                "a[download]",
                "button:has(mat-icon:text-is('download'))"
            ]
            
            for sel in selectors:
                try:
                    btn = last_response.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=2000)
                        logger.info("download_button_clicked_playwright", selector=sel)
                        return True
                except Exception:
                    continue
            
            return False
        except Exception as e:
            logger.warn("download_handler_failed", error=str(e))
            return False

    @staticmethod
    async def fallback_download_via_fetch(page: Page, url: str, dest_path: str) -> bool:
        try:
            logger.info("download_fallback_fetch_initiated", url=url[:50])
            response = await page.request.get(url)
            
            if response.status == 200:
                body = await response.body()
                with open(dest_path, "wb") as f:
                    f.write(body)
                logger.info("download_fallback_fetch_success", dest=dest_path, size=len(body))
                return True
            else:
                logger.warn("download_fallback_fetch_http_error", status=response.status)
                return False
                
        except Exception as e:
            logger.error("download_fallback_fetch_exception", error=str(e))
            return False