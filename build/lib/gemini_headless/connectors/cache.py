# gemini_headless/connectors/cache.py
"""
Cache for storing discovered UI selectors
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

# Import config and logger from siblings
from .config import Config
from .logger import logger

class SelectorCache:
    """
    Manages a persistent JSON cache for UI selectors to speed up location.
    Reads cache configuration from Config class.
    """
    
    def __init__(self):
        self.cache_path = Path(Config.CACHE_PATH)
        self.cache_ttl = Config.GH_INPUT_CACHE_TTL
        self.is_enabled = Config.GH_INPUT_CACHE
        # Store data in {key: {selector: str, timestamp: float}} format
        self._cache_data: Dict[str, Dict[str, Any]] = {} 
        self._load_cache()

    def _load_cache(self):
        """Load cache from disk if enabled and file exists."""
        if not self.is_enabled:
            logger.debug("cache_disabled_skipping_load")
            return
        
        if not self.cache_path.exists():
            logger.debug("cache_file_not_found", path=str(self.cache_path))
            return
        
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._cache_data = data
                    logger.info("cache_loaded", path=str(self.cache_path), entries=len(data))
                else:
                    logger.warn("cache_invalid_format", path=str(self.cache_path))
        except Exception as e:
            logger.error("cache_load_error", path=str(self.cache_path), error=str(e))

    def _save_cache(self):
        """Save cache to disk if enabled."""
        if not self.is_enabled:
            return
        
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache_data, f, indent=2)
            logger.debug("cache_saved", path=str(self.cache_path), entries=len(self._cache_data))
        except Exception as e:
            logger.error("cache_save_error", path=str(self.cache_path), error=str(e))

    def get(self, key: str) -> Optional[str]:
        """Get a selector from cache, checking TTL."""
        if not self.is_enabled or not key:
            return None
        
        entry_data = self._cache_data.get(key)
        if not entry_data or not isinstance(entry_data, dict):
            return None
        
        try:
            selector = entry_data.get("selector")
            timestamp = float(entry_data.get("timestamp", 0))
            
            if not selector or not timestamp:
                return None
            
            age_seconds = time.time() - timestamp
            if age_seconds > self.cache_ttl:
                logger.debug("cache_ttl_expired", key=key, age_seconds=round(age_seconds))
                # Evict expired entry
                self._cache_data.pop(key, None)
                # We don't save here, 'get' shouldn't have disk side effects
                return None
            
            logger.debug("cache_hit", key=key, selector=selector)
            return str(selector)
            
        except Exception as e:
            logger.warn("cache_get_error", key=key, error=str(e))
            return None

    def set(self, key: str, selector: str):
        """Set a selector in the cache and save."""
        if not self.is_enabled or not key or not selector:
            return
        
        try:
            self._cache_data[key] = {
                "selector": selector,
                "timestamp": time.time()
            }
            logger.debug("cache_set", key=key, selector=selector)
            self._save_cache()
        except Exception as e:
            logger.error("cache_set_error", key=key, error=str(e))