"""
Configuration module for Gemini Headless Connector
Centralizes all environment variables and constants
"""

import os
from pathlib import Path
from typing import List


class Config:
    """Configuration class for all settings"""
    
    # --- Environment helpers ---
    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except Exception:
            return default

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        v = (os.getenv(name, "").strip().lower())
        return v in {"1", "true", "yes", "y", "on"} if v else default

    # --- Main configuration ---
    GH_INPUT_MAX_ATTEMPTS = _env_int.__func__("GH_INPUT_MAX_ATTEMPTS", 2)
    GH_LOCATE_FILL_TIMEOUT_MS = _env_int.__func__("GH_LOCATE_FILL_TIMEOUT_MS", 4000)
    GH_SUBMIT_BUTTON_CLICK_TIMEOUT_MS = _env_int.__func__(
        "GH_SUBMIT_BUTTON_CLICK_TIMEOUT_MS", 20000
    )
    GH_RETRY_DELAY_MS = _env_int.__func__("GH_RETRY_DELAY_MS", 300)
    GH_POST_UPLOAD_STABILIZE_MS = _env_int.__func__("GH_POST_UPLOAD_STABILIZE_MS", 10000)
    GH_SUBMIT_SELECTOR_OVERRIDE = os.getenv("GH_SUBMIT_SELECTOR_OVERRIDE", "").strip()
    
    # --- Cache configuration ---
    GH_INPUT_CACHE = _env_bool.__func__("GH_INPUT_CACHE", True)
    GH_INPUT_CACHE_TTL = _env_int.__func__("GH_INPUT_CACHE_TTL", 7 * 24 * 3600)
    GH_INPUT_CACHE_DIR = os.getenv("GH_INPUT_CACHE_DIR", str(Path.home() / ".gh_cache"))
    CACHE_PATH = str(Path(GH_INPUT_CACHE_DIR) / "input_locator_cache_v2.json")
    
    # --- Timing patch configuration ---
    GH_TIMING_PATCH_ENABLED = _env_bool.__func__("GH_TIMING_PATCH_ENABLED", True)
    
    # --- Timeouts configuration ---
    DEFAULT_TIMEOUT_MS = 30000
    UPLOAD_TIMEOUT_MS = 120000
    CHAT_READY_TIMEOUT_MS = 15000
    POST_UPLOAD_WAIT_MS = 2000
    UI_STABILIZE_MS = 300


class Selectors:
    """CSS selectors for various UI elements"""
    
    # --- Input zone selectors ---
    INPUT_SELECTORS = [
        'div[role="textbox"][aria-label="Demander à Gemini"]',
        'div[role="textbox"][contenteditable="true"]',
        'textarea[aria-label*="prompt" i]',
        '[data-testid*="chat-input"]',
        '[contenteditable="true"][aria-label]',
        'textarea[aria-label]',
        'main div[role="textbox"]',
        'main textarea',
        'textarea',
        '[contenteditable="true"]',
    ]
    
    # --- Submit button selectors ---
    SUBMIT_BUTTON_SELECTORS: List[str] = [
        # Exact matches (français/anglais)
        'button[aria-label="Envoyer le message"]',
        'button[aria-label="Send message"]',
        'button[aria-label*="Envoyer"]',
        'button[aria-label*="Send"]',
        
        # Data attributes (Google/Gemini style)
        'button[data-testid="send-button"]',
        'button[data-testid*="send"]',
        'button[jsname="x8hlje"]',
        
        # Type attributes
        'button[type="submit"]',
        
        # Heuristic: Button with SVG
        'button:has(svg)',
        
        # Flexible role-based
        '[role="button"][aria-label*="Send"]',
        '[role="button"][aria-label*="Envoyer"]',
        
        # Fallback: Last button in conversation
        'button:last-of-type',
    ]
    
    # --- File upload detection selectors ---
    FILE_UPLOAD_DETECTION_SELECTORS = [
        # Primary: Official attachment indicators
        'div[aria-label*="fichier attaché" i]',
        'div[aria-label*="file attached" i]',
        'div[aria-label*="attachment" i]',
        
        # Images/thumbnails
        'img[aria-label*="Fichier image" i]',
        'img[aria-label*="uploaded" i]',
        'img.attachment-thumbnail',
        
        # Chips/badges
        '[data-testid*="attachment"]',
        '[data-testid*="uploaded"]',
        'mat-chip-row',
        '.mdc-chip',
        
        # Generic video/file indicators
        'div[class*="upload"]',
        'div[class*="media"]',
        'div.multimodal-chunk',
        
        # Fallback video preview
        'video[class*="preview"]',
        'canvas[aria-label*="video" i]',
    ]
    
    # --- Chat interface selectors ---
    CHAT_READY_SELECTORS = [
        'button[aria-label*="microphone" i]',
        'button[aria-label*="Send message"]',
        'button[aria-label*="Envoyer"]',
        'button[data-testid*="send"]',
        'button[type="submit"]',
        '[role="button"][aria-label*="Send"]',
    ]
    
    @classmethod
    def get_submit_button_selector_string(cls) -> str:
        """Get submit button selectors as a comma-separated string for Playwright"""
        return ", ".join(cls.SUBMIT_BUTTON_SELECTORS)
