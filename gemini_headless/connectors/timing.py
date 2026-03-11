"""
Timing and wait utilities for UI synchronization
"""

import asyncio
import time
import re
from typing import Optional, Tuple, Callable, Dict

from playwright.async_api import Page, TimeoutError as PWTimeout

from .config import Config, Selectors
from .logger import logger


class SemanticTimeout:
    """
    Intelligence: Calcule des timeouts dynamiques basés sur la sémantique du prompt.
    """
    
    # Mots-clés suggérant une réponse complexe/longue
    HEAVY_KEYWORDS = [
        "code", "python", "script", "programme", "algorithm", 
        "analyse", "tableau", "comparatif", "liste exhaustive",
        "détaille", "explique", "tutoriel", "guide", "essai",
        "summary", "summarize", "rewrite", "translate"
    ]
    
    # Mots-clés suggérant une réponse rapide
    LIGHT_KEYWORDS = [
        "date", "heure", "qui est", "bref", "oui ou non", 
        "define", "what is", "short", "quick"
    ]

    @staticmethod
    def calculate_generation_timeout(prompt: str, base_timeout_s: float = 60.0) -> float:
        """
        Estime le temps nécessaire pour la génération.
        """
        if not prompt:
            return base_timeout_s

        p_lower = prompt.lower()
        score = 1.0
        
        # 1. Analyse de la longueur
        length_factor = min(len(prompt) / 100.0, 2.0) # Cap à +200% pour la longueur
        score += length_factor * 0.1

        # 2. Analyse Sémantique
        heavy_hits = sum(1 for k in SemanticTimeout.HEAVY_KEYWORDS if k in p_lower)
        light_hits = sum(1 for k in SemanticTimeout.LIGHT_KEYWORDS if k in p_lower)
        
        # Bonus pour la complexité
        if heavy_hits > 0:
            score += (heavy_hits * 0.5) # +50% par mot clé complexe
            # Plancher minimum pour les requêtes complexes
            base_timeout_s = max(base_timeout_s, 120.0) 
            
        # Malus pour la simplicité
        if light_hits > 0 and heavy_hits == 0:
            score *= 0.6 # -40% si c'est une question triviale
        
        # Calcul final avec bornes de sécurité
        final_timeout = base_timeout_s * score
        
        # Limites Hard (Min 30s, Max 10min)
        final_timeout = max(30.0, min(final_timeout, 600.0))
        
        logger.debug("semantic_timeout_calculated", 
                     prompt_snippet=prompt[:30], 
                     score=f"{score:.2f}", 
                     final_timeout=f"{final_timeout:.1f}s")
                     
        return final_timeout


class TimingUtils:
    """Utilities for timing and UI synchronization"""
    
    @staticmethod
    async def wait_for_idle_network(
        page: Page, 
        timeout_ms: int = 5000,
        idle_time_ms: int = 500
    ) -> bool:
        """
        Wait for network to become idle
        """
        try:
            logger.debug("wait_network_idle_start", 
                        timeout_ms=timeout_ms,
                        idle_time_ms=idle_time_ms)
            
            await page.wait_for_load_state(
                "networkidle",
                timeout=timeout_ms
            )
            
            # Additional wait for complete idle
            await asyncio.sleep(idle_time_ms / 1000)
            
            logger.debug("wait_network_idle_complete")
            return True
            
        except PWTimeout:
            logger.warn("wait_network_idle_timeout", timeout_ms=timeout_ms)
            return False
        except Exception as e:
            logger.error("wait_network_idle_error", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_dom_stable(
        page: Page,
        timeout_ms: int = 3000,
        check_interval_ms: int = 100,
        stable_count: int = 3
    ) -> bool:
        """
        Wait for DOM to stop changing
        """
        try:
            logger.debug("wait_dom_stable_start", timeout_ms=timeout_ms)
            
            # JavaScript to get a simple DOM signature
            get_dom_signature = """
                () => {
                    const elements = document.querySelectorAll('*');
                    return {
                        count: elements.length,
                        text_length: document.body?.innerText?.length || 0,
                        html_length: document.body?.innerHTML?.length || 0
                    };
                }
            """
            
            start_time = time.time()
            last_signature = None
            stable_checks = 0
            
            while (time.time() - start_time) * 1000 < timeout_ms:
                current_signature = await page.evaluate(get_dom_signature)
                
                if last_signature == current_signature:
                    stable_checks += 1
                    if stable_checks >= stable_count:
                        logger.debug("wait_dom_stable_complete", 
                                   stable_after_ms=int((time.time() - start_time) * 1000))
                        return True
                else:
                    stable_checks = 0
                
                last_signature = current_signature
                await asyncio.sleep(check_interval_ms / 1000)
            
            logger.warn("wait_dom_stable_timeout", timeout_ms=timeout_ms)
            return False
            
        except Exception as e:
            logger.error("wait_dom_stable_error", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_react_input_cycle(
        page: Page,
        timeout_ms: int = 1000
    ) -> bool:
        """
        Wait for React input processing cycle to complete
        """
        try:
            logger.debug("wait_react_cycle_start")
            
            # Use requestAnimationFrame to wait for next render cycle
            await page.evaluate("""
                () => new Promise(resolve => {
                    requestAnimationFrame(() => {
                        requestAnimationFrame(resolve);
                    });
                })
            """)
            
            # Small additional delay for React reconciliation
            await asyncio.sleep(0.05)
            
            logger.debug("wait_react_cycle_complete")
            return True
            
        except Exception as e:
            logger.error("wait_react_cycle_error", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_button_ready(
        page: Page,
        timeout_ms: int = 5000
    ) -> bool:
        """
        Wait for submit button to be ready and clickable
        """
        try:
            logger.debug("wait_button_ready_start")
            
            # Check if any submit button is visible and enabled
            button_ready_script = f"""
                () => {{
                    const selectors = {Selectors.SUBMIT_BUTTON_SELECTORS};
                    for (const selector of selectors) {{
                        const button = document.querySelector(selector);
                        if (button && 
                            !button.disabled && 
                            button.offsetParent !== null &&
                            window.getComputedStyle(button).visibility !== 'hidden') {{
                            return true;
                        }}
                    }}
                    return false;
                }}
            """
            
            start_time = time.time()
            while (time.time() - start_time) * 1000 < timeout_ms:
                is_ready = await page.evaluate(button_ready_script)
                if is_ready:
                    logger.debug("wait_button_ready_complete")
                    return True
                await asyncio.sleep(0.1)
            
            logger.warn("wait_button_ready_timeout", timeout_ms=timeout_ms)
            return False
            
        except Exception as e:
            logger.error("wait_button_ready_error", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_upload_complete(
        page: Page,
        timeout_ms: int = Config.UPLOAD_TIMEOUT_MS
    ) -> bool:
        """
        Wait for file upload to complete
        """
        try:
            logger.info("wait_upload_complete_start", timeout_ms=timeout_ms)
            
            # Build detection script
            detection_script = f"""
                () => {{
                    const selectors = {Selectors.FILE_UPLOAD_DETECTION_SELECTORS};
                    for (const selector of selectors) {{
                        const elements = document.querySelectorAll(selector);
                        if (elements.length > 0) {{
                            return {{
                                detected: true,
                                selector: selector,
                                count: elements.length
                            }};
                        }}
                    }}
                    return {{ detected: false }};
                }}
            """
            
            start_time = time.time()
            last_log_time = start_time
            
            while (time.time() - start_time) * 1000 < timeout_ms:
                result = await page.evaluate(detection_script)
                
                if result["detected"]:
                    logger.info("wait_upload_complete_detected",
                               selector=result.get("selector"),
                               count=result.get("count"),
                               elapsed_ms=int((time.time() - start_time) * 1000))
                    
                    # Additional stabilization wait
                    await asyncio.sleep(Config.POST_UPLOAD_WAIT_MS / 1000)
                    return True
                
                # Log progress every 5 seconds
                if time.time() - last_log_time > 5:
                    logger.debug("wait_upload_complete_checking",
                               elapsed_s=int(time.time() - start_time))
                    last_log_time = time.time()
                
                await asyncio.sleep(0.5)
            
            logger.warn("wait_upload_complete_timeout",
                       timeout_ms=timeout_ms)
            return False
            
        except Exception as e:
            logger.error("wait_upload_complete_error", error=str(e))
            return False
    
    @staticmethod
    async def wait_for_ui_ready(
        page: Page,
        timeout_ms: int = Config.CHAT_READY_TIMEOUT_MS,
        include_network: bool = True,
        include_dom: bool = True,
        include_button: bool = True
    ) -> bool:
        """
        Comprehensive UI readiness check
        """
        try:
            logger.info("wait_ui_ready_start",
                       timeout_ms=timeout_ms,
                       checks={
                           "network": include_network,
                           "dom": include_dom,
                           "button": include_button
                       })
            
            start_time = time.time()
            remaining_time = lambda: max(0, timeout_ms - int((time.time() - start_time) * 1000))
            
            # Network idle check
            if include_network and remaining_time() > 0:
                network_ok = await TimingUtils.wait_for_idle_network(
                    page,
                    timeout_ms=min(remaining_time(), 5000)
                )
                if not network_ok:
                    logger.warn("wait_ui_ready_network_failed")
            
            # DOM stability check
            if include_dom and remaining_time() > 0:
                dom_ok = await TimingUtils.wait_for_dom_stable(
                    page,
                    timeout_ms=min(remaining_time(), 3000)
                )
                if not dom_ok:
                    logger.warn("wait_ui_ready_dom_failed")
            
            # Button ready check
            if include_button and remaining_time() > 0:
                button_ok = await TimingUtils.wait_for_button_ready(
                    page,
                    timeout_ms=min(remaining_time(), 2000)
                )
                if not button_ok:
                    logger.warn("wait_ui_ready_button_failed")
                    return False
            
            # React cycle wait
            if remaining_time() > 0:
                await TimingUtils.wait_for_react_input_cycle(page)
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info("wait_ui_ready_complete", elapsed_ms=elapsed_ms)
            return True
            
        except Exception as e:
            logger.error("wait_ui_ready_error", error=str(e))
            return False
    
    @staticmethod
    def create_timeout_tracker(total_timeout_ms: int) -> Callable[[], int]:
        """
        Create a function to track remaining timeout
        """
        start_time = time.perf_counter()
        
        def time_left() -> int:
            elapsed = (time.perf_counter() - start_time) * 1000
            return max(0, int(total_timeout_ms - elapsed))
        
        return time_left