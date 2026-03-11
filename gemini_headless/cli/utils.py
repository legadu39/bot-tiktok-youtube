# gemini_headless/cli/utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import sys
import json
import time
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Any

# ============================================================================
# ===== CORRECTION IMPORTATION PLAYWRIGHT =====
# Ligne originale (incorrecte) :
# from playwright.async_api import Page, Locator, PlaywrightError
# Ligne corrigée (importe 'Error' et l'alias 'PlaywrightError') :
from playwright.async_api import Page, Locator, Error as PlaywrightError
# ============================================================================

# Importation relative pour jlog
try:
    from ..collect.utils.logs import jlog
except ImportError:
    # Fallback si ce module est utilisé d'une manière inattendue
    def jlog(evt: str, **kw):
        payload = {"evt": evt, "ts": time.time(), "pid": os.getpid(), **kw}
        try:
            print(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")), 
                  file=sys.stderr, flush=True)
        except Exception:
            print(f"[FALLBACK_JLOG] {evt}: {kw}", file=sys.stderr, flush=True)


# ============================================================================
# PATCH 9 - LOGIQUE DE RÉPERTOIRE SIGNAL
# ============================================================================

def _resolve_signal_dir() -> Path:
    """
    PATCH 9 - Résout le répertoire des signaux avec 4 niveaux de fallback robuste.
    """
    
    # ========== NIVEAU 1 : Variable d'environnement primaire ==========\
    signal_dir_env = os.getenv("GH_SIGNAL_DIR", "").strip()
    if signal_dir_env:
        try:
            candidate = Path(signal_dir_env).resolve().absolute()
            if candidate.exists() and candidate.is_dir():
                jlog(
                    "patch9_signaldir_resolved",
                    **{"level": "INFO", "reason": "env_primary", "path": str(candidate)},
                )
                return candidate
        except Exception:
            pass # Continuer vers le niveau suivant

    # ========== NIVEAU 2 : Variable d'environnement de secours ==========\
    signal_dir_backup_env = os.getenv("GH_SIGNAL_DIR_BACKUP", "").strip()
    if signal_dir_backup_env:
        try:
            candidate = Path(signal_dir_backup_env).resolve().absolute()
            if candidate.exists() and candidate.is_dir():
                jlog(
                    "patch9_signaldir_resolved",
                    **{"level": "INFO", "reason": "env_backup", "path": str(candidate)},
                )
                return candidate
        except Exception:
            pass # Continuer vers le niveau suivant
            
    # ========== NIVEAU 3 : Détection du répertoire parental (mode auto) ==========\
    try:
        current_dir = Path(__file__).resolve().parent
        # Remonter jusqu'à trouver 'gemini_headless', puis son parent, puis 'var/signals'
        # Note: Ceci est une hypothèse sur la structure
        project_root = None
        for p in current_dir.parents:
            if p.name == 'gemini_headless':
                project_root = p.parent
                break
        
        if project_root:
            candidate = project_root / "var" / "signals"
            if candidate.exists() and candidate.is_dir():
                jlog(
                    "patch9_signaldir_resolved",
                    **{"level": "WARN", "reason": "parent_detection", "path": str(candidate)},
                )
                return candidate
        
        jlog("patch9_signaldir_parent_detection_error", **{"error": "Project root not found", "level": "DEBUG"})
    except Exception as e:
        jlog(
            "patch9_signaldir_parent_detection_error",
            **{"error": str(e), "level": "DEBUG"},
        )
    
    # ========== NIVEAU 4 : Fallback sécurisé au répertoire temporaire ==========\
    try:
        tempdir = Path(tempfile.gettempdir()) / "geminiheadless-signals"
        tempdir.mkdir(parents=True, exist_ok=True)
        resolved = tempdir.resolve().absolute()
        jlog(
            "patch9_signaldir_resolved",
            **{"level": "WARN", "reason": "fallback_tempdir", "path": str(resolved)},
        )
        return resolved
    except OSError as e:
        jlog(
            "patch9_signaldir_tempdir_creation_error",
            **{"error": str(e), "level": "ERROR"},
        )
        # Ultime fallback sans vérification
        return Path(tempfile.gettempdir()) / "geminiheadless-signals-emergency"

# ============================================================================
# AUTRES UTILITAIRES
# ============================================================================

def get_browser_executable_path() -> Optional[str]:
    """Trouve un exécutable de navigateur compatible."""
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    potential_paths_win = [
        Path(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        Path(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        Path(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
        Path(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
        Path(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        Path(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"),
        Path(program_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        Path(program_files_x86, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ]
    potential_paths_linux = [
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
        Path("/snap/bin/chromium"),
        Path("/usr/bin/microsoft-edge-stable"),
        Path("/usr/bin/microsoft-edge"),
        Path("/usr/bin/brave-browser-stable"),
        Path("/usr/bin/brave-browser"),
    ]
    potential_paths_mac = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path(os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
        Path(os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
        Path(os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")),
    ]
    if sys.platform == "win32":
        candidates = potential_paths_win
    elif sys.platform == "darwin":
        candidates = potential_paths_mac
    else:
        candidates = potential_paths_linux
    for path in candidates:
        try:
            if path.exists() and path.is_file():
                jlog("browser_found", path=str(path), level="INFO")
                return str(path)
        except OSError:
            pass
    jlog("browser_not_found", paths_checked=len(candidates), platform=sys.platform, level="CRITICAL")
    return None


async def try_selector_parallel_batch(page: Page, selectors: List[str], 
                                      timeout_per_selector_ms: int = 300,
                                      total_timeout_ms: int = 2000) -> Optional[Tuple[str, Locator]]:
    """
    Test multiple selectors in PARALLEL instead of sequentially.
    Returns: (winning_selector, locator) ou None
    """
    jlog("parallel_heuristic_test_start", 
         selector_count=len(selectors),
         total_timeout_ms=total_timeout_ms,
         per_selector_ms=timeout_per_selector_ms,
         level="DEBUG")
    
    async def test_single_selector(selector: str, index: int) -> Optional[Tuple[str, Locator]]:
        """Test a single selector concurrently."""
        try:
            jlog("parallel_heuristic_try", index=index, selector=selector[:50], level="DEBUG")
            locator = page.locator(selector).first
            
            # Quick visibility check
            await locator.wait_for(state="visible", timeout=timeout_per_selector_ms)
            
            jlog("parallel_heuristic_found", index=index, selector=selector[:50], level="DEBUG")
            return (selector, locator)
        except (PlaywrightError, AssertionError):
            return None  # Silent fail, try next
        except Exception as e:
            jlog("parallel_heuristic_error", index=index, 
                 error=str(e)[:50], level="DEBUG")
            return None
    
    try:
        # Create all test tasks
        tasks = [test_single_selector(sel, i) for i, sel in enumerate(selectors)]
        
        # Run all in parallel with global timeout
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=False),
            timeout=total_timeout_ms / 1000.0
        )
        
        # Return first successful result
        for result in results:
            if result is not None:
                selector, locator = result
                jlog("parallel_heuristic_winner", 
                     winning_selector=selector[:50],
                     attempts=len(selectors),
                     level="INFO")
                return selector, locator
        
        jlog("parallel_heuristic_no_winner", 
             attempts=len(selectors),
             level="DEBUG")
        return None
        
    except asyncio.TimeoutError:
        jlog("parallel_heuristic_timeout", 
             total_timeout_ms=total_timeout_ms,
             level="WARN")
        return None
    except Exception as e:
        jlog("parallel_heuristic_error", 
             error=str(e)[:100],
             level="WARN")
        return None

async def save_failure_artifacts(page: Page, profile: Any, reason: str):
    """Saves screenshot and HTML on failure. (Accepts SandboxProfile as Any)"""
    try:
        ts = int(time.time())
        # Assumes profile object has a 'profile_dir' attribute
        artifacts_dir = Path(profile.profile_dir) / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        
        ss_path = artifacts_dir / f"fail_{ts}_{reason}.png"
        await page.screenshot(path=str(ss_path), full_page=True)
        
        html_path = artifacts_dir / f"fail_{ts}_{reason}.html"
        html_content = await page.content()
        html_path.write_text(html_content, encoding="utf-8")
        
        jlog("save_failure_artifacts_success", reason=reason, screenshot=str(ss_path), html=str(html_path))
    except Exception as e:
        jlog("save_failure_artifacts_error", reason=reason, error=str(e).splitlines()[0], level="ERROR")