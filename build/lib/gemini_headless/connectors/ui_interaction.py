### gemini_headless/connectors/ui_interaction.py
"""
UI interaction utilities for input and submission with Adaptive Intelligence
Updates V_Final: Smart Hybrid Typing Strategy (PID Controller + Lag-Aware)
"""

import asyncio
import time
import json
import math
from pathlib import Path
from typing import Optional, Tuple, List, Dict, ClassVar

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
    """Handles input field interactions with probabilistic selector ranking and PID typing"""
    
    _selector_scores: ClassVar[Dict[str, int]] = {}
    _scores_file: ClassVar[Path] = Path("selector_scores.json")
    _clear_prefs: ClassVar[Dict[str, str]] = {}
    _clear_prefs_file: ClassVar[Path] = Path("clear_prefs.json")
    
    _loaded: ClassVar[bool] = False
    
    def __init__(self, cache: Optional[SelectorCache] = None):
        self.cache = cache or SelectorCache()
        if not InputHandler._loaded:
            self._load_persistent_scores()
            InputHandler._loaded = True
    
    @classmethod
    def _load_persistent_scores(cls):
        try:
            if cls._scores_file.exists():
                with open(cls._scores_file, "r", encoding="utf-8") as f:
                    saved_scores = json.load(f)
                    cls._selector_scores.update(saved_scores)
            
            if cls._clear_prefs_file.exists():
                with open(cls._clear_prefs_file, "r", encoding="utf-8") as f:
                    saved_prefs = json.load(f)
                    cls._clear_prefs.update(saved_prefs)
                    
            logger.info("input_handler_loaded", 
                        scores=len(cls._selector_scores), 
                        prefs=len(cls._clear_prefs))
        except Exception as e:
            logger.warn("selector_scores_load_failed", error=str(e))

    def _save_persistent_scores(self):
        try:
            with open(self._scores_file, "w", encoding="utf-8") as f:
                json.dump(self._selector_scores, f, indent=2)
            
            with open(self._clear_prefs_file, "w", encoding="utf-8") as f:
                json.dump(self._clear_prefs, f, indent=2)
        except Exception as e:
            logger.debug("selector_scores_save_failed", error=str(e))

    def _get_sorted_selectors(self, base_selectors: List[str]) -> List[str]:
        return sorted(
            base_selectors,
            key=lambda s: self._selector_scores.get(s, 0),
            reverse=True
        )

    def _update_score(self, selector: str, success: bool):
        current = self._selector_scores.get(selector, 0)
        if success:
            self._selector_scores[selector] = min(current + 1, 20)
        else:
            self._selector_scores[selector] = max(current - 5, -10)
        self._save_persistent_scores()
    
    def _update_clear_pref(self, selector: str, method: str):
        if selector and method:
            self._clear_prefs[selector] = method
            self._save_persistent_scores()

    async def locate_input_field(
        self,
        page: Page,
        timeout_ms: int = Config.GH_LOCATE_FILL_TIMEOUT_MS,
        use_cache: bool = True,
        extra_selectors: Optional[List[str]] = None
    ) -> Tuple[Optional[ElementHandle], Optional[str]]:
        try:
            url = page.url
            
            if use_cache:
                cached_selector = self.cache.get(url)
                if cached_selector:
                    try:
                        element = await page.query_selector(cached_selector)
                        if element and await element.is_visible():
                            logger.info("input_located_from_cache", selector=cached_selector)
                            self._update_score(cached_selector, True)
                            return element, cached_selector
                    except Exception as e:
                        logger.warn("cached_selector_failed", selector=cached_selector, error=str(e))
            
            candidates = list(Selectors.INPUT_SELECTORS)
            if extra_selectors:
                candidates = [s for s in extra_selectors if s not in candidates] + candidates
            
            viable_candidates = [s for s in candidates if self._selector_scores.get(s, 0) > -10]
            if not viable_candidates:
                viable_candidates = candidates
                
            sorted_candidates = self._get_sorted_selectors(viable_candidates)
            t_start = time.monotonic()
            
            for selector in sorted_candidates:
                if (time.monotonic() - t_start) * 1000 > timeout_ms:
                    break
                
                try:
                    score = self._selector_scores.get(selector, 0)
                    step_timeout = 200 if score < 0 else 500
                    
                    element = await page.wait_for_selector(
                        selector,
                        state="visible",
                        timeout=min(step_timeout, timeout_ms)
                    )
                    
                    if element:
                        logger.info("input_located", selector=selector, score=score)
                        self._update_score(selector, True)
                        if use_cache:
                            self.cache.set(url, selector)
                        return element, selector
                        
                except PWTimeout:
                    self._update_score(selector, False)
                    continue
                except Exception as e:
                    logger.debug("selector_error", selector=selector, error=str(e))
                    self._update_score(selector, False)
                    continue
            
            logger.error("input_not_found", tried=len(sorted_candidates))
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
        """Fallback method using JS Injection for extreme lag or huge payloads."""
        try:
            await page.evaluate("""(data) => {
                const { text, element } = data;
                // Clipboard Event simulation
                try {
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const event = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
                    element.dispatchEvent(event);
                } catch (e) { }
                
                // Direct Insertion Fallback
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
        Type text using PID Controller Logic.
        Adapts typing speed to browser latency in real-time.
        """
        try:
            if not element and selector:
                element = await page.query_selector(selector)
            
            if not element:
                logger.error("type_text_no_element")
                return False
            
            await element.focus()
            
            # 1. Complexity & Initial Latency Check
            t_start = time.perf_counter()
            try:
                await page.evaluate("1+1")
                latency_ms = (time.perf_counter() - t_start) * 1000
            except Exception:
                latency_ms = 9999
            
            complexity_score = len(text) + (text.count('\n') * 20)
            
            # If extremely laggy or huge text, go straight to JS
            if latency_ms > 200 or complexity_score > 2000:
                logger.info("typing_strategy_fast_mode", reason="initial_check", latency=f"{latency_ms:.1f}ms")
                return await self._type_via_js_injection(page, text, element)

            # 2. PID-Controlled Human Typing
            logger.info("typing_strategy_pid_mode", length=len(text), start_latency=f"{latency_ms:.1f}ms")
            
            target_latency = 50.0  # We want the browser to respond within 50ms
            current_delay = float(delay_ms)
            
            # Split into chunks to adjust speed periodically
            chunk_size = 50 
            chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            
            for i, chunk in enumerate(chunks):
                # Type the chunk
                await page.keyboard.type(chunk, delay=int(current_delay))
                
                # Handle newlines explicitly if needed (often handled by type, but ensuring Shift+Enter if separate lines)
                # (Assuming simple typing here, standard behavior)

                # 3. Measurement & Adjustment (PID Loop)
                # Every chunk, we measure the "pressure" on the browser
                if i < len(chunks) - 1: # Don't measure on last chunk
                    m_start = time.perf_counter()
                    try:
                        await page.evaluate("1") # Micro-ping
                        actual_latency = (time.perf_counter() - m_start) * 1000
                        
                        # Emergency Cutoff
                        if actual_latency > 300:
                            logger.warn("pid_latency_critical_switch_to_js", latency=f"{actual_latency:.1f}ms")
                            remaining_text = "".join(chunks[i+1:])
                            return await self._type_via_js_injection(page, remaining_text, element)
                        
                        # Proportional Control
                        error = actual_latency - target_latency
                        
                        # If error > 0 (lagging), increase delay (slow down)
                        # If error < 0 (fast), decrease delay (speed up)
                        correction = error * 0.5 
                        current_delay += correction
                        
                        # Clamp delay
                        current_delay = max(5.0, min(current_delay, 150.0))
                        
                    except Exception:
                        # If measurement fails, assume lag and slow down
                        current_delay += 20
            
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