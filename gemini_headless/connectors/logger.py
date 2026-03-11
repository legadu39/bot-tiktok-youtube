"""
Logging utilities for Gemini Headless Connector
"""

import json
import sys
import time
from typing import Any, Optional


class Logger:
    """Logger wrapper with jlog support"""
    
    _instance: Optional['Logger'] = None
    _jlog_func = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_jlog()
        return cls._instance
    
    def _initialize_jlog(self):
        """Initialize jlog function with fallback"""
        try:
            # Try different import paths
            try:
                from ..collect.utils.logs import jlog
                self._jlog_func = jlog
            except ImportError:
                try:
                    from ..utils.logs import jlog
                    self._jlog_func = jlog
                except ImportError:
                    try:
                        from utils.logs import jlog
                        self._jlog_func = jlog
                    except ImportError:
                        # Fallback implementation
                        self._jlog_func = self._default_jlog
        except Exception:
            self._jlog_func = self._default_jlog
    
    @staticmethod
    def _default_jlog(evt: str, **payload):
        """Default jlog implementation when imports fail"""
        try:
            payload.setdefault("ts", time.time())
            print(json.dumps({"evt": evt, **payload}), file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            pass
    
    def log(self, event: str, **kwargs):
        """Main logging method"""
        if self._jlog_func:
            self._jlog_func(event, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Debug level logging"""
        self.log(f"debug_{message}", level="DEBUG", **kwargs)
    
    def info(self, message: str, **kwargs):
        """Info level logging"""
        self.log(message, level="INFO", **kwargs)
    
    def warn(self, message: str, **kwargs):
        """Warning level logging"""
        self.log(message, level="WARN", **kwargs)
    
    def error(self, message: str, **kwargs):
        """Error level logging"""
        self.log(message, level="ERROR", **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Critical level logging"""
        self.log(message, level="CRITICAL", **kwargs)


# Global logger instance
logger = Logger()