# gemini_headless/cli/upload_handler.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional, List, Tuple

from playwright.async_api import (
    Page, FileChooser, TimeoutError as PWTimeoutError, 
    Error as PlaywrightError, Locator
)

# Imports relatifs
from ..collect.utils.logs import jlog
from ..connectors.config import Selectors as ConnectorSelectors
from .utils import try_selector_parallel_batch
from .upload_cache import (
    load_behavior_cache_intelligent,
    save_behavior_cache_validated,
    invalidate_behavior_cache,
    DEFAULT_PLUS_BUTTON_SELECTORS,
    DEFAULT_IMPORT_OPTION_SELECTORS
)

# Variable globale pour stocker la raison de l'échec (spécifique à ce module)
failure_reason = "unknown_init"

# --- Fonctions de Validation Comportementale ---

async def validate_plus_button_click(page: Page, plus_locator: Locator, import_option_selectors: List[str], strategy_name: str, plus_selector_str: str) -> bool:
    jlog("upload_validate_plus_attempt", strategy=strategy_name, selector=plus_selector_str, level="DEBUG")
    clicked = False
    try:
        try:
            # Correction RuntimeWarning: 'await' manquant
            el_html = await plus_locator.evaluate("el => el.outerHTML")
            loc = page.locator(el_html).first
            
            await loc.hover(timeout=500)
            await asyncio.sleep(0.1)
        except Exception:
            pass
        try:
            await plus_locator.focus(timeout=500)
            await asyncio.sleep(0.1)
        except Exception:
            pass
        try:
            await plus_locator.click(timeout=1500, delay=50)
            clicked = True
        except PlaywrightError:
            jlog("upload_validate_plus_click_failed_std", strategy=strategy_name, selector=plus_selector_str, level="DEBUG")
            try:
                await plus_locator.dispatch_event('click', timeout=1000)
                clicked = True
            except PlaywrightError:
                jlog("upload_validate_plus_click_failed", strategy=strategy_name, selector=plus_selector_str, level="WARN")
                return False
        if clicked:
            await asyncio.sleep(0.3)
            combined_import_selector = ", ".join(import_option_selectors)
            import_option_locator = page.locator(combined_import_selector).first
            try:
                await import_option_locator.wait_for(state="visible", timeout=2000) 
                jlog("upload_validate_plus_success", strategy=strategy_name, selector=plus_selector_str, level="INFO")
                return True
            except PWTimeoutError:
                jlog("upload_validate_plus_fail_option_not_visible", strategy=strategy_name, selector=plus_selector_str, level="WARN")
                return False
        return False
    except Exception as e:
        jlog("upload_validate_plus_unexpected_error", strategy=strategy_name, selector=plus_selector_str, error=str(e).split('\n')[0], level="WARN")
        return False

async def try_click_import_option_validation(page: Page, locator: Locator, strategy_name: str, selector: str) -> Optional[FileChooser]:
    file_chooser: Optional[FileChooser] = None
    jlog("upload_validate_import_option_attempt", strategy=strategy_name, selector=selector, level="DEBUG")
    try:
        is_visible = False
        try:
            is_visible = await locator.is_visible(timeout=500)
        except Exception:
            pass
        if not is_visible:
            jlog("upload_validate_import_skip_not_visible", strategy=strategy_name, selector=selector, level="DEBUG")
            return None
        try:
            await locator.hover(timeout=500)
            await asyncio.sleep(0.1)
            jlog("upload_validate_import_hovered", strategy=strategy_name, level="DEBUG")
        except Exception as hover_err:
            jlog("upload_validate_import_hover_failed", strategy=strategy_name, error=str(hover_err).split('\n')[0], level="DEBUG")
        try:
            await locator.focus(timeout=500)
            await asyncio.sleep(0.1)
            jlog("upload_validate_import_focused", strategy=strategy_name, level="DEBUG")
        except Exception as focus_err:
            jlog("upload_validate_import_focus_failed", strategy=strategy_name, error=str(focus_err).split('\n')[0], level="DEBUG")
        
        async with page.expect_file_chooser(timeout=2500) as fc_info:
            clicked = False
            click_method_used = "none"
            try:
                await locator.click(timeout=2000, delay=100)
                clicked = True
                click_method_used = "click_with_delay"
                jlog("upload_validate_import_click_method", method=click_method_used, strategy=strategy_name, level="DEBUG")
            except PlaywrightError as click_err:
                jlog("upload_validate_import_click_failed_trying_dispatch", strategy=strategy_name, error=str(click_err).split('\n')[0], level="DEBUG")
                try:
                    await locator.dispatch_event('click', timeout=1500)
                    clicked = True
                    click_method_used = "dispatch_event"
                    jlog("upload_validate_import_click_method", method=click_method_used, strategy=strategy_name, level="DEBUG")
                except PlaywrightError as dispatch_err:
                    jlog("upload_validate_import_dispatch_failed_trying_enter", strategy=strategy_name, error=str(dispatch_err).split('\n')[0], level="DEBUG")
                    try:
                        await locator.focus(timeout=300)
                        await asyncio.sleep(0.1)
                        await page.keyboard.press("Enter", delay=100)
                        clicked = True
                        click_method_used = "focus_and_enter"
                        jlog("upload_validate_import_click_method", method=click_method_used, strategy=strategy_name, level="DEBUG")
                    except Exception as enter_err:
                        jlog("upload_validate_import_focus_enter_failed", strategy=strategy_name, error=str(enter_err).split('\n')[0], level="WARN")
                        pass
        if clicked:
            try:
                await asyncio.sleep(0.2)
                file_chooser = await fc_info.value
                if file_chooser:
                    jlog("upload_validate_import_success", strategy=strategy_name, selector=selector, method_used=click_method_used, level="INFO")
                    return file_chooser
                else:
                    jlog("upload_validate_import_click_ok_but_no_fc_value", strategy=strategy_name, selector=selector, method_used=click_method_used, level="WARN")
                    return None
            except PWTimeoutError:
                jlog("upload_validate_import_fc_value_timeout", strategy=strategy_name, selector=selector, method_used=click_method_used, level="WARN")
                return None
            except Exception as fc_val_err:
                jlog("upload_validate_import_fc_value_error", strategy=strategy_name, selector=selector, method_used=click_method_used, error=str(fc_val_err).split('\n')[0], level="WARN")
                return None
        else:
            jlog("upload_validate_import_all_click_methods_failed", strategy=strategy_name, selector=selector, level="WARN")
            return None
    except PWTimeoutError:
        jlog("upload_validate_import_no_filechooser", strategy=strategy_name, selector=selector, level="DEBUG")
        return None
    except Exception as e:
        jlog("upload_validate_import_unexpected_error", strategy=strategy_name, selector=selector, error=str(e).split('\n')[0], level="WARN")
        return None

# ============================================================================
# LOGIQUE D'UPLOAD DE FICHIER (Fonction principale)
# ============================================================================

async def handle_file_upload(page: Page, file_path: str, explicit_selectors_str: Optional[str], profile_dir: Path) -> Tuple[bool, str]:
    """
    Revised file upload with INTELLIGENT CACHE strategy.
    Returns: (success, failure_reason)
    """
    global failure_reason
    failure_reason = "unknown_upload_init" # Reset reason
    
    filepath = file_path 
    
    jlog("file_upload_started_robust_v8_two_phase", path=filepath, level="INFO")
    
    # ✅ PATCH POINT 1: INTELLIGENT CACHE LOAD
    cached_plus, cached_import, cache_confidence = load_behavior_cache_intelligent(profile_dir)
    jlog("cache_confidence_loaded", confidence=cache_confidence, level="INFO")
    
    found_file_chooser: Optional[FileChooser] = None
    final_plus_selector: Optional[str] = None
    final_import_selector: Optional[str] = None
    strategy_used = "none_yet"
    
    plus_button_locator: Optional[Locator] = None
    plus_strategy_used = None
    
    # Parsing des sélecteurs explicites (logique d'origine conservée, utilise ';;')
    explicit_plus: Optional[str] = None
    explicit_import: Optional[str] = None
    if explicit_selectors_str and ";;" in explicit_selectors_str:
        parts = explicit_selectors_str.split(";;", 1)
        explicit_plus = parts[0].strip()
        explicit_import = parts[1].strip()
        jlog("using_cli_upload_selectors_pair", plus=explicit_plus, import_opt=explicit_import, level="INFO")
    elif explicit_selectors_str:
        explicit_plus = explicit_selectors_str.strip()
        jlog("using_cli_upload_selector_plus_only", plus=explicit_plus, level="INFO")
    
    try:
        jlog("file_upload_initial_wait", duration_ms=750, level="DEBUG")
        await page.wait_for_timeout(750)
    except Exception as wait_err:
        jlog("file_upload_initial_wait_error", error=str(wait_err), level="WARN")
    
    # ========== PHASE 1: FIND PLUS BUTTON ==========
    
    # 1a. Try cached selector (if high confidence)
    if cached_plus and cache_confidence in ["proven", "explicit", "auto_created"]:
        jlog("upload_phase1_attempt_strategy", 
             strategy="behavior_cache",
             confidence=cache_confidence,
             level="DEBUG")
        
        locator = page.locator(cached_plus).first
        try:
            await locator.wait_for(state="visible", timeout=1500)
            
            # Utiliser cached_import si disponible, sinon les defaults
            import_options = ([cached_import] if cached_import else []) + DEFAULT_IMPORT_OPTION_SELECTORS
            
            if await validate_plus_button_click(page, locator, import_options, 
                                              "behavior_cache", cached_plus):
                plus_button_locator = locator
                final_plus_selector = cached_plus
                final_import_selector = cached_import
                plus_strategy_used = "behavior_cache"
                jlog("upload_phase1_success", strategy=plus_strategy_used, 
                     selector=final_plus_selector[:50], level="INFO")
        except Exception as cache_plus_err:
            jlog("behavior_cache_plus_error", 
                 selector=cached_plus[:50],
                 error=str(cache_plus_err).split('\n')[0],
                 level="DEBUG")
            invalidate_behavior_cache(profile_dir) # Invalidation si échec
            # Fall through to next strategy

    # 1b. Try explicit selector
    if not plus_button_locator and explicit_plus:
        jlog("upload_phase1_attempt_strategy", 
             strategy="explicit_plus",
             level="DEBUG")
        
        locator = page.locator(explicit_plus).first
        try:
            await locator.wait_for(state="visible", timeout=2000)
            
            import_options = ([explicit_import] if explicit_import else []) + DEFAULT_IMPORT_OPTION_SELECTORS
            
            if await validate_plus_button_click(page, locator, import_options,
                                              "explicit", explicit_plus):
                plus_button_locator = locator
                final_plus_selector = explicit_plus
                final_import_selector = explicit_import
                plus_strategy_used = "explicit"
                jlog("upload_phase1_success", strategy=plus_strategy_used,
                     selector=final_plus_selector[:50], level="INFO")
        except Exception as explicit_plus_err:
            jlog("upload_explicit_plus_error",
                 selector=explicit_plus[:50],
                 error=str(explicit_plus_err).split('\n')[0],
                 level="DEBUG")
    
    # ✅ PATCH POINT 2: PARALLEL HEURISTICS (fast fallback)
    if not plus_button_locator:
        jlog("upload_phase1_attempt_strategy",
             strategy="heuristics_parallel",
             selector_count=len(DEFAULT_PLUS_BUTTON_SELECTORS),
             level="DEBUG")
        
        result = await try_selector_parallel_batch(
            page,
            DEFAULT_PLUS_BUTTON_SELECTORS,
            timeout_per_selector_ms=250,  # Faster per-selector
            total_timeout_ms=1500  # Total ~1.5s for all 6 heuristics
        )
        
        if result:
            selector, locator = result
            
            # On a trouvé le bouton, maintenant on vérifie s'il ouvre le menu
            import_options = ([explicit_import] if explicit_import else []) + DEFAULT_IMPORT_OPTION_SELECTORS
            if await validate_plus_button_click(page, locator, import_options,
                                              "heuristics_parallel", selector):
                plus_button_locator = locator
                final_plus_selector = selector
                final_import_selector = None # Sera trouvé en phase 2
                plus_strategy_used = "heuristics_parallel"
                jlog("upload_phase1_success", strategy=plus_strategy_used,
                     selector=final_plus_selector[:50], level="INFO")
    
    # 1d. Last resort: exhaustive behavioral search (code d'origine conservé)
    if not plus_button_locator:
        jlog("upload_phase1_attempt_strategy", strategy="behavioral_exhaustive_plus", level="DEBUG")
        try:
            input_box_selector = ", ".join(ConnectorSelectors.INPUT_SELECTORS)
            
            await page.locator(input_box_selector).first.wait_for(state="visible", timeout=3000)
            # Retrait du :visible ici
            exhaustive_plus_selector = f"button:near({input_box_selector}, 150)" 
            buttons_locator = page.locator(exhaustive_plus_selector)
            button_count = await buttons_locator.count()
            jlog("behavioral_exhaustive_plus_candidates", count=button_count, selector=exhaustive_plus_selector, level="DEBUG")
            for i in range(button_count):
                locator = buttons_locator.nth(i)
                current_selector_str = f"{exhaustive_plus_selector} >> nth={i}"
                jlog("behavioral_exhaustive_plus_trying", index=i, selector=current_selector_str, level="DEBUG")
                import_options_to_check = ([explicit_import] if explicit_import else []) + DEFAULT_IMPORT_OPTION_SELECTORS
                if await validate_plus_button_click(page, locator, import_options_to_check, f"exhaustive_plus_{i}", current_selector_str):
                    plus_button_locator = locator
                    try:
                        aria = await locator.get_attribute("aria-label", timeout=50)
                        final_plus_selector = f"button[aria-label='{aria}']" if aria else current_selector_str
                    except Exception:
                        final_plus_selector = current_selector_str
                    plus_strategy_used = f"exhaustive_plus_{i}"
                    jlog("upload_phase1_success", strategy=plus_strategy_used, selector=final_plus_selector, level="INFO")
                    break
        except Exception as exhaustive_plus_err:
            jlog("behavioral_exhaustive_plus_error", error=str(exhaustive_plus_err).split('\n')[0], level="WARN")

    
    if not plus_button_locator or not final_plus_selector:
        jlog("upload_phase1_failed_all_strategies", level="ERROR")
        failure_reason = "upload_plus_button_not_found_v8"
        return False, failure_reason
    
    # ========== PHASE 2: FIND IMPORT OPTION ==========
    
    import_option_locator: Optional[Locator] = None
    import_strategy_used = None
    found_file_chooser: Optional[FileChooser] = None
    
    # 2a. Try cached import selector
    if cached_import and plus_strategy_used == "behavior_cache":
        final_import_selector = cached_import
        jlog("upload_phase2_attempt_strategy",
             strategy="behavior_cache_import",
             selector=final_import_selector[:50],
             level="DEBUG")
        
        locator = page.locator(final_import_selector).first
        found_file_chooser = await try_click_import_option_validation(
            page, locator, "behavior_cache_import", final_import_selector
        )
        
        if found_file_chooser:
            import_option_locator = locator
            import_strategy_used = "behavior_cache_import"
            jlog("upload_phase2_success", strategy=import_strategy_used,
                 selector=final_import_selector[:50], level="INFO")
        else:
            invalidate_behavior_cache(profile_dir)
            final_import_selector = None 
    
    # 2b. Try explicit import selector
    if not import_option_locator and explicit_import: 
        final_import_selector = explicit_import
        jlog("upload_phase2_attempt_strategy",
             strategy="explicit_import",
             selector=final_import_selector[:50],
             level="DEBUG")
        
        locator = page.locator(final_import_selector).first
        found_file_chooser = await try_click_import_option_validation(
            page, locator, "explicit_import", final_import_selector
        )
        
        if found_file_chooser:
            import_option_locator = locator
            import_strategy_used = "explicit_import"
            jlog("upload_phase2_success", strategy=import_strategy_used,
                 selector=final_import_selector[:50], level="INFO")
    
    # ✅ PATCH POINT 3: PARALLEL IMPORT HEURISTICS (if needed)
    if not import_option_locator:
        jlog("upload_phase2_attempt_strategy",
             strategy="import_heuristics_parallel",
             selector_count=len(DEFAULT_IMPORT_OPTION_SELECTORS),
             level="DEBUG")
        
        result = await try_selector_parallel_batch(
            page,
            DEFAULT_IMPORT_OPTION_SELECTORS,
            timeout_per_selector_ms=250,
            total_timeout_ms=1500
        )
        
        if result:
            selector, locator = result
            
            found_file_chooser = await try_click_import_option_validation(
                page, locator, "import_heuristics_parallel", selector
            )
            
            if found_file_chooser:
                import_option_locator = locator
                final_import_selector = selector
                import_strategy_used = "import_heuristics_parallel"
                jlog("upload_phase2_success", strategy=import_strategy_used,
                     selector=final_import_selector[:50], level="INFO")
    
    # 2d. Exhaustive import (code d'origine conservé)
    if not import_option_locator:
        jlog("upload_phase2_attempt_strategy", strategy="behavioral_exhaustive_import", level="DEBUG")
        # Retrait du :visible ici
        menu_selector = "[role='menu'], [role='listbox'], div[class*='menu']"
        menu_locator = page.locator(menu_selector).first
        try:
            menu_count = await menu_locator.count()
        except Exception:
            menu_count = 0
        search_base_locator = menu_locator if menu_count > 0 else page
        base_label = menu_selector if menu_count > 0 else "page"
        # Retrait du :visible ici
        exhaustive_import_selector = "button, [role='menuitem']"
        options_locator = search_base_locator.locator(exhaustive_import_selector)
        option_count = await options_locator.count()
        jlog("behavioral_exhaustive_import_candidates", count=option_count, base_selector=(menu_selector if menu_count > 0 else "page"), level="DEBUG")
        for i in range(option_count): # Correction: itérer sur option_count, pas button_count
            locator = options_locator.nth(i)
            current_selector_str = f"{base_label} >> {exhaustive_import_selector} >> nth={i}"
            try:
                item_text = (await locator.text_content(timeout=50)) or ""
                item_aria = (await locator.get_attribute("aria-label", timeout=50)) or ""
                jlog("behavioral_exhaustive_import_trying", index=i, text=item_text[:30], aria=item_aria[:40], level="DEBUG")
            except Exception:
                jlog("behavioral_exhaustive_import_trying", index=i, text="<error>", aria="<error>", level="DEBUG")

            found_file_chooser = await try_click_import_option_validation(page, locator, f"exhaustive_import_{i}", current_selector_str)
            if found_file_chooser:
                import_option_locator = locator
                try:
                    aria = await locator.get_attribute("aria-label", timeout=50)
                    text_content = await locator.text_content(timeout=50)
                    final_import_selector = f"button[aria-label='{aria}']" if aria else (f"button:has-text('{text_content}')" if text_content else current_selector_str)
                except Exception:
                    final_import_selector = current_selector_str
                import_strategy_used = f"exhaustive_import_{i}"
                strategy_used = f"{plus_strategy_used} -> {import_strategy_used}"
                jlog("upload_phase2_success", strategy=import_strategy_used, selector=final_import_selector, level="INFO")
                save_behavior_cache_validated(profile_dir, final_plus_selector, final_import_selector) # Sauvegarde ici aussi en cas de succès
                break

    if not import_option_locator or not final_import_selector:
        jlog("upload_phase2_failed_all_strategies", level="ERROR")
        failure_reason = "upload_import_option_not_found_v8"
        
        if plus_strategy_used == "behavior_cache":
            invalidate_behavior_cache(profile_dir)
        return False, failure_reason
    
    # ========== PHASE 3: SET FILE & WAIT CONFIRMATION ==========
    
    # ✅ PATCH POINT 4: SAVE VALIDATED CACHE 
    # Sauf si la stratégie exhaustive l'a déjà fait.
    if plus_strategy_used != "behavioral_exhaustive_plus" and (import_strategy_used not in ["behavior_cache_import", "explicit_import"]):
        save_behavior_cache_validated(
            profile_dir,
            final_plus_selector,
            final_import_selector,
            validation_passed=True
        )

    strategy_used = f"{plus_strategy_used} -> {import_strategy_used}" # Redefine strategy_used after finalization
    
    try:
        jlog("file_chooser_obtained", strategy=strategy_used,
             plus_selector=final_plus_selector[:50],
             import_selector=final_import_selector[:50],
             level="INFO")
        
        file_to_upload = Path(filepath)
        if not file_to_upload.is_file():
            jlog("file_path_invalid_or_not_found", path=filepath, level="ERROR")
            failure_reason = "file_not_found"
            raise FileNotFoundError(f"Le fichier spécifié n'existe pas: {filepath}")
        
        await found_file_chooser.set_files(file_to_upload)
        jlog("file_chooser_set_files_success", ok=True,
             file=file_to_upload.name, level="INFO")
        
        confirmation_selectors = [
            'div.multimodal-chunk', 'mat-chip-row', 'div.file-preview-container',
            'img[alt*="Preview"]', 'div[aria-label*="file"]', '[data-testid="file-attachment-chip"]',
        ]
        combined_selector_visible = ", ".join(confirmation_selectors)
        spinner_selector_disappear = 'div.multimodal-chunk mat-progress-spinner'
        
        jlog("waiting_for_upload_confirmation", selectors_sample=confirmation_selectors[:2],
             timeout_s=180, level="INFO")
        
        visible_confirmation = page.locator(combined_selector_visible).first
        await visible_confirmation.wait_for(state='visible', timeout=180000)
        jlog("file_upload_confirmation_visible", level="INFO")
        
        # Wait for spinner to disappear
        try:
            spinner = page.locator(spinner_selector_disappear).first
            is_spinner_visible = False
            try:
                is_spinner_visible = await spinner.is_visible(timeout=1000)
            except PWTimeoutError:
                pass
            
            if is_spinner_visible:
                jlog("waiting_for_upload_spinner_to_disappear", level="INFO")
                await spinner.wait_for(state='hidden', timeout=120000)
                jlog("upload_spinner_disappeared", level="INFO")
            else:
                jlog("upload_spinner_not_found_or_already_hidden", level="DEBUG")
        except PWTimeoutError:
            jlog("upload_spinner_did_not_disappear_timeout", level="WARN")
        except Exception as spinner_err:
            jlog("upload_spinner_wait_error", error=str(spinner_err).split('\n')[0], level="WARN")
        
        return True, "" # Succès
        
    except FileNotFoundError:
        return False, failure_reason # Déjà loggué
    except PWTimeoutError as timeout_err:
        error_msg = str(timeout_err).split('\n')[0]
        is_confirm_timeout = 'wait_for(state=\'visible\'' in error_msg
        failure_reason = "upload_confirmation_timeout" if is_confirm_timeout else "upload_finalization_timeout"
        
        jlog("failure_reason", strategy=strategy_used,
             plus_selector=final_plus_selector,
             import_selector=final_import_selector,
             error=error_msg,
             level="ERROR")
        return False, failure_reason
    except PlaywrightError as upload_pw_err:
        error_msg = str(upload_pw_err).split('\n')[0]
        jlog("file_upload_finalization_playwright_error",
             strategy=strategy_used,
             plus_selector=final_plus_selector,
             import_selector=final_import_selector,
             error=error_msg,
             level="ERROR")
        failure_reason = "upload_finalization_pw_error"
        return False, failure_reason
    except Exception as err:
        error_msg = str(err).split('\n')[0]
        jlog("file_upload_finalization_unexpected_error",
             strategy=strategy_used,
             error=error_msg,
             error_type=type(err).__name__,
             level="ERROR")
        failure_reason = "upload_finalization_unexpected_error"
        return False, failure_reason