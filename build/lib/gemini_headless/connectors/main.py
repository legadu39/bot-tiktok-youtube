### gemini_headless/connectors/main.py
"""
Main orchestrator for sending prompts to Gemini
Updates V_Final: Smart Timeout Calculation (Adaptive Prediction)
"""

import asyncio
import time
from typing import Optional, List, Tuple

from playwright.async_api import Page, Error as PlaywrightError

from .config import Config
from .logger import logger
from .cache import SelectorCache
from .timing import TimingUtils
from .ui_interaction import InputHandler, SubmitHandler, UploadHandler


class GeminiPromptSender:
    """Main class for sending prompts to Gemini interface"""
    
    def __init__(self, cache: Optional[SelectorCache] = None):
        """
        Initialize the prompt sender
        
        Args:
            cache: Optional selector cache instance
        """
        self.cache = cache or SelectorCache()
        self.input_handler = InputHandler(self.cache)
        self.submit_handler = SubmitHandler()
        self.upload_handler = UploadHandler()
        self.timing = TimingUtils()
    
    def _calculate_smart_timeout(self, prompt: str, has_files: bool, base_timeout: int) -> int:
        """
        Heuristic: Predict needed time based on prompt complexity.
        Overrides base_timeout only if predicted need is higher.
        """
        if base_timeout != Config.DEFAULT_TIMEOUT_MS:
            # User provided a specific custom timeout, respect it.
            return base_timeout
            
        # Base cost: 15s
        predicted_ms = 15_000
        
        # 1. Length Factor: 50ms per char
        predicted_ms += len(prompt) * 50
        
        # 2. Complexity Keywords
        keywords = ["code", "script", "génère", "full", "analyse", "tableau", "complex", "review"]
        complexity_hits = sum(1 for w in keywords if w in prompt.lower())
        predicted_ms += complexity_hits * 30_000
        
        # 3. File Factor
        if has_files:
            predicted_ms += 60_000
            
        # Bounds: Min 20s, Max 5min (for the send interaction part, not generation)
        # Note: This controls the interaction/waiting, generation timeout is handled by Orchestrator.
        final_ms = max(20_000, min(predicted_ms, 300_000))
        
        if final_ms > base_timeout:
            logger.info("smart_timeout_adjusted", original=base_timeout, new=final_ms, reason="complexity_heuristic")
            return final_ms
            
        return base_timeout

    async def send_prompt(
        self,
        page: Page,
        prompt: str,
        files_to_upload: Optional[List[str]] = None,
        timeout_ms: int = Config.DEFAULT_TIMEOUT_MS,
        clear_input: bool = True,
        wait_for_ready: bool = True,
        is_post_upload: bool = False
    ) -> bool:
        """
        Send a prompt to Gemini with optional file uploads
        """
        # --- INTELLIGENCE: Adaptive Timeout ---
        # Calculate dynamic timeout based on complexity
        timeout_ms = self._calculate_smart_timeout(prompt, bool(files_to_upload), timeout_ms)
        
        start_time = time.perf_counter()
        time_tracker = TimingUtils.create_timeout_tracker(timeout_ms)
        
        logger.info("send_prompt_start",
                   prompt_length=len(prompt),
                   has_files=bool(files_to_upload),
                   file_count=len(files_to_upload) if files_to_upload else 0,
                   timeout_ms=timeout_ms)
        
        try:
            # Wait for UI to be ready if requested
            if wait_for_ready:
                ui_ready = await self.timing.wait_for_ui_ready(
                    page,
                    timeout_ms=min(time_tracker(), Config.CHAT_READY_TIMEOUT_MS)
                )
                if not ui_ready:
                    logger.warn("ui_not_ready_proceeding_anyway")
            
            # Handle file uploads if provided
            if files_to_upload:
                success = await self._handle_file_upload(
                    page, 
                    files_to_upload,
                    time_tracker
                )
                if not success:
                    logger.error("file_upload_failed")
                    return False
            
            # Send the text prompt
            final_is_post_upload = bool(files_to_upload) or is_post_upload

            return await self._send_text_prompt(
                page,
                prompt,
                time_tracker,
                clear_input=clear_input,
                is_post_upload=final_is_post_upload
            )
            
        except Exception as e:
            logger.error("send_prompt_error",
                        error=str(e),
                        error_type=type(e).__name__)
            return False
        
        finally:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info("send_prompt_complete",
                       success=False,  # Will be overridden if successful (logic flows don't update this var but logs are atomic)
                       elapsed_ms=elapsed_ms)
    
    async def _handle_file_upload(
        self,
        page: Page,
        file_paths: List[str],
        time_tracker
    ) -> bool:
        """
        Handle file upload process
        """
        logger.info("file_upload_process_start", file_count=len(file_paths))
        
        # Upload files
        upload_success = await self.upload_handler.upload_files(
            page,
            file_paths,
            timeout_ms=min(time_tracker(), Config.UPLOAD_TIMEOUT_MS)
        )
        
        if not upload_success:
            return False
        
        # Wait for upload to complete
        upload_complete = await self.upload_handler.detect_upload_complete(
            page,
            timeout_ms=min(time_tracker(), Config.UPLOAD_TIMEOUT_MS)
        )
        
        if not upload_complete:
            logger.warn("upload_detection_timeout_proceeding")
        
        # Additional stabilization after upload
        await asyncio.sleep(Config.POST_UPLOAD_WAIT_MS / 1000)
        
        logger.info("file_upload_process_complete")
        return True
    
    async def _send_text_prompt(
        self,
        page: Page,
        prompt: str,
        time_tracker,
        clear_input: bool = True,
        is_post_upload: bool = False
    ) -> bool:
        """
        Send text prompt with retry logic
        """
        max_attempts = Config.GH_INPUT_MAX_ATTEMPTS
        
        for attempt in range(1, max_attempts + 1):
            logger.info("send_text_attempt",
                       attempt=attempt,
                       max_attempts=max_attempts,
                       is_post_upload=is_post_upload)
            
            # Check remaining time
            if time_tracker() < 3000:
                logger.error("insufficient_time_remaining",
                           remaining_ms=time_tracker())
                return False
            
            try:
                # Locate input field
                element, selector = await self.input_handler.locate_input_field(
                    page,
                    timeout_ms=min(time_tracker(), Config.GH_LOCATE_FILL_TIMEOUT_MS)
                )
                
                if not element:
                    logger.error("input_field_not_found", attempt=attempt)
                    if attempt < max_attempts:
                        await asyncio.sleep(Config.GH_RETRY_DELAY_MS / 1000)
                        continue
                    return False
                
                # Clear input if requested
                if clear_input:
                    await self.input_handler.clear_input(page, element)
                
                # Focus and type text
                await element.focus()
                
                # Wait for React cycle before typing
                if Config.GH_TIMING_PATCH_ENABLED:
                    await self.timing.wait_for_react_input_cycle(page)
                
                # Type the prompt
                type_success = await self.input_handler.type_text(
                    page,
                    prompt,
                    element=element
                )
                
                if not type_success:
                    logger.error("type_text_failed", attempt=attempt)
                    if attempt < max_attempts:
                        await asyncio.sleep(Config.GH_RETRY_DELAY_MS / 1000)
                        continue
                    return False
                
                # Wait for UI to be ready for submission
                if Config.GH_TIMING_PATCH_ENABLED:
                    await self._wait_for_submit_ready(page, is_post_upload)
                
                # Submit the prompt
                submit_success = await self._submit_prompt(
                    page,
                    time_tracker,
                    attempt
                )
                
                if submit_success:
                    logger.info("send_text_success",
                               attempt=attempt,
                               selector_used=selector)
                    return True
                
                # Retry if not last attempt
                if attempt < max_attempts:
                    logger.warn("submit_failed_retrying",
                               attempt=attempt)
                    await asyncio.sleep(Config.GH_RETRY_DELAY_MS / 1000)
                
            except PlaywrightError as e:
                error_msg = str(e).lower()
                is_critical = any(word in error_msg for word in 
                                 ["closed", "navigat", "destroyed"])
                
                if is_critical:
                    logger.error("critical_playwright_error",
                               error=str(e),
                               attempt=attempt)
                    return False
                
                logger.warn("playwright_error_retrying",
                           error=str(e),
                           attempt=attempt)
                
                if attempt < max_attempts:
                    await asyncio.sleep(Config.GH_RETRY_DELAY_MS / 1000)
            
            except Exception as e:
                logger.error("unexpected_error",
                           error=str(e),
                           error_type=type(e).__name__,
                           attempt=attempt)
                
                if attempt < max_attempts:
                    await asyncio.sleep(Config.GH_RETRY_DELAY_MS / 1000)
        
        logger.error("all_attempts_failed", max_attempts=max_attempts)
        return False
    
    async def _wait_for_submit_ready(
        self,
        page: Page,
        is_post_upload: bool
    ) -> None:
        """
        Wait for UI to be ready for submission
        """
        if not Config.GH_TIMING_PATCH_ENABLED:
            return
        
        logger.debug("wait_submit_ready_start", is_post_upload=is_post_upload)
        
        # Phase 1: Network stabilization
        await self.timing.wait_for_idle_network(page, timeout_ms=2000)
        
        # Phase 2: React input cycle
        await self.timing.wait_for_react_input_cycle(page)
        
        # Phase 3: Button responsiveness check
        is_responsive = await self.submit_handler.test_button_responsive(page)
        
        if not is_responsive:
            logger.warn("button_not_responsive_waiting")
            await asyncio.sleep(0.5)
        
        logger.debug("wait_submit_ready_complete")
    
    async def _submit_prompt(
        self,
        page: Page,
        time_tracker,
        attempt: int
    ) -> bool:
        """
        Submit the prompt using various methods
        """
        submit_timeout = min(
            time_tracker(),
            Config.GH_SUBMIT_BUTTON_CLICK_TIMEOUT_MS
        )
        
        # Try button click first
        success, method = await self.submit_handler.submit_by_button_click(
            page,
            timeout_ms=submit_timeout
        )
        
        if success:
            logger.info("submit_successful",
                       method=method,
                       attempt=attempt)
            return True
        
        # Fallback to Enter key
        logger.warn("button_click_failed_trying_enter",
                   previous_method=method)
        
        success, method = await self.submit_handler.submit_by_enter_key(page)
        
        if success:
            logger.info("submit_successful",
                       method=method,
                       attempt=attempt)
            return True
        
        logger.error("all_submit_methods_failed",
                    attempt=attempt)
        return False
    
    async def fast_send_prompt(
        self,
        page: Page,
        prompt: str,
        timeout_ms: int = Config.DEFAULT_TIMEOUT_MS,
        is_post_upload: bool = False
    ) -> bool:
        """
        Fast version of send_prompt with minimal checks
        """
        return await self.send_prompt(
            page=page,
            prompt=prompt,
            files_to_upload=None,
            timeout_ms=timeout_ms,
            clear_input=True,
            wait_for_ready=False,
            is_post_upload=is_post_upload
        )


# Module-level function for backward compatibility
async def fast_send_prompt(
    page: Page,
    prompt: str,
    timeout_ms: int = Config.DEFAULT_TIMEOUT_MS,
    is_post_upload: bool = False
) -> bool:
    """
    Fast send prompt - module-level function for backward compatibility
    """
    sender = GeminiPromptSender()
    return await sender.fast_send_prompt(page, prompt, timeout_ms, is_post_upload=is_post_upload)


# Export main classes and functions
__all__ = [
    'GeminiPromptSender',
    'fast_send_prompt',
    'Config',
    'SelectorCache',
    'InputHandler',
    'SubmitHandler',
    'UploadHandler',
    'TimingUtils'
]