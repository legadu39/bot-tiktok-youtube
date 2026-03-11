# gemini_headless/cli/upload_cache.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import time
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

from ..collect.utils.logs import jlog

# ============================================================================
# SECTION CONSTANTS - CACHE INTELLIGENCE SYSTEM (PATCH INTELLIGENT)
# ============================================================================

UPLOAD_BEHAVIOR_CACHE_FILE = ".upload_selectors_cache_v2.json"
CACHE_METADATA_FILE = ".cache_diagnostics.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 jours (validity period)

# Sélecteurs "proven" (validés depuis des centaines de runs)
PROVEN_PLUS_SELECTOR = 'button:near(div[role="textbox"][aria-label="Demander à Gemini"], div[role="textbox"][contenteditable="true"], textarea[aria-label*="prompt" i], [data-testid*="chat-input"], [contenteditable="true"][aria-label], textarea[aria-label], main div[role="textbox"], main textarea, textarea, [contenteditable="true"], 150) >> nth=2'
PROVEN_IMPORT_SELECTOR = 'button:has-text("Importer des fichiers")'

# Score de confiance du cache
CACHE_CONFIDENCE_LEVELS = {
    "proven": 100,      # De run précédent réussi
    "auto_created": 85, # Auto-généré avec sélecteurs validés
    "heuristic": 40,    # Trouvé via heuristiques (faible confiance)
    "explicit": 95      # Fourni explicitement par CLI
}

# ============================================================================
# ===== CORRECTION : AJOUT DES LISTES DE SÉLECTEURS MANQUANTES =====
# Ces listes étaient manquantes et provoquaient une ImportError
# dans upload_handler.py.
# ============================================================================

# Sélecteurs plus réalistes / compatibles Playwright
DEFAULT_PLUS_BUTTON_SELECTORS = [
    'button[aria-label*="joindre" i][aria-label*="fichier" i]',
    'button[aria-label*="attach" i][aria-label*="file" i]',
    'button:has-text("+")',
    'button:has-text("Ajouter")',
    'button:has-text("Add")',
    'button:has(svg[aria-label*="add" i])',
    'button:near(div[role="textbox"], 75)', 
]
DEFAULT_IMPORT_OPTION_SELECTORS = [
    'button:has-text("Importer des fichiers")',
    'button[aria-label*="Importer des fichiers" i]',
    '[role="menuitem"]:has-text("Importer des fichiers")',
    'button:has-text("Import files")',
    'button[aria-label*="Import files" i]',
    '[role="menuitem"]:has-text("Import files")',
]
# ===== FIN DE LA CORRECTION =====

# --- FIN SECTION CONSTANTS PATCH INTELLIGENT ---


def compute_cache_hash(plus_selector: str, import_selector: str) -> str:
    """Compute hash of selectors for integrity checking."""
    data = f"{plus_selector}|{import_selector}".encode('utf-8')
    return hashlib.sha256(data).hexdigest()[:16]

def load_cache_metadata(profile_dir: Path) -> Dict[str, Any]:
    """Load cache metadata for diagnostics and validation."""
    metadata_path = profile_dir / CACHE_METADATA_FILE
    if metadata_path.exists():
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            jlog("cache_metadata_load_error", error=str(e), level="WARN")
    return {}

def save_cache_metadata(profile_dir: Path, metadata: Dict[str, Any]):
    """Save cache metadata for diagnostics."""
    metadata_path = profile_dir / CACHE_METADATA_FILE
    metadata['last_updated'] = time.time()
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        jlog("cache_metadata_save_error", error=str(e), level="WARN")

def is_cache_valid(cache_data: Dict[str, Any]) -> bool:
    """
    Validate cache:
    - Check TTL (7 jours)
    - Check integrity hash
    - Check completeness
    """
    if not cache_data:
        return False
    
    plus_sel = cache_data.get("plus_button_selector", "")
    import_sel = cache_data.get("import_option_selector", "")
    
    # Check completeness
    if not plus_sel or not import_sel:
        jlog("cache_validation_failed", reason="incomplete", level="DEBUG")
        return False
    
    # Check TTL
    if "timestamp" in cache_data:
        age_seconds = time.time() - cache_data.get("timestamp", 0)
        ttl_exceeded = age_seconds > CACHE_TTL_SECONDS
        if ttl_exceeded:
            jlog("cache_validation_failed", reason="ttl_exceeded", 
                 age_days=age_seconds / 86400, level="DEBUG")
            return False
    
    # Check integrity
    stored_hash = cache_data.get("integrity_hash", "")
    expected_hash = compute_cache_hash(plus_sel, import_sel)
    if stored_hash and stored_hash != expected_hash:
        jlog("cache_validation_failed", reason="integrity_mismatch", level="WARN")
        return False
    
    return True

def load_behavior_cache_intelligent(profile_dir: Path) -> Tuple[Optional[str], Optional[str], str]:
    """
    Intelligent cache loading with multi-level fallback:
    Returns: (plus_selector, import_selector, confidence_level)
    """
    cache_path = profile_dir / UPLOAD_BEHAVIOR_CACHE_FILE
    metadata = load_cache_metadata(profile_dir)
    
    # Level 1: Try to load existing cache
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            if is_cache_valid(cache_data):
                plus_sel = cache_data.get("plus_button_selector")
                import_sel = cache_data.get("import_option_selector")
                confidence = cache_data.get("confidence", "proven")
                
                # Update metadata (success count)
                metadata['cache_hits'] = metadata.get('cache_hits', 0) + 1
                metadata['last_hit'] = time.time()
                save_cache_metadata(profile_dir, metadata)
                
                jlog("behavior_cache_loaded_intelligent", 
                     plus_selector=plus_sel[:50],
                     import_selector=import_sel[:50],
                     confidence=confidence,
                     cache_age_days=(time.time() - cache_data.get('timestamp', 0)) / 86400,
                     level="INFO")
                
                return plus_sel, import_sel, confidence
        except Exception as e:
            jlog("behavior_cache_load_error", error=str(e), 
                 path=str(cache_path), level="WARN")
            # Fall through to auto-create
    
    # Level 2: Cache not found or invalid → Auto-create with proven selectors
    jlog("behavior_cache_auto_create_start", reason="cache_missing_or_invalid", level="INFO")
    
    plus_selector = PROVEN_PLUS_SELECTOR
    import_selector = PROVEN_IMPORT_SELECTOR
    confidence = "auto_created"
    
    # Save auto-created cache
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "plus_button_selector": plus_selector,
            "import_option_selector": import_selector,
            "timestamp": time.time(),
            "confidence": confidence,
            "source": "auto_created_intelligent",
            "version": "2.0",
            "integrity_hash": compute_cache_hash(plus_selector, import_selector),
            "platform": sys.platform,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "auto_created": True
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        # Update metadata
        metadata['auto_created_count'] = metadata.get('auto_created_count', 0) + 1
        metadata['last_auto_created'] = time.time()
        save_cache_metadata(profile_dir, metadata)
        
        jlog("behavior_cache_auto_created_success", 
             plus_selector=plus_selector[:50],
             import_selector=import_selector[:50],
             level="INFO")
        
    except Exception as e:
        jlog("behavior_cache_auto_create_error", error=str(e), level="WARN")
        # Even if save fails, return the selectors for this run
    
    return plus_selector, import_selector, confidence

def save_behavior_cache_validated(profile_dir: Path, plus_selector: str, 
                                   import_selector: str, validation_passed: bool = True):
    """
    Save cache with metadata:
    - Only save if validation_passed (real selector, tested in current run)
    - Add success tracking
    - Update TTL timestamp
    """
    if not validation_passed:
        jlog("behavior_cache_not_saved", reason="validation_failed", level="DEBUG")
        return
    
    cache_path = profile_dir / UPLOAD_BEHAVIOR_CACHE_FILE
    metadata = load_cache_metadata(profile_dir)
    
    try:
        cache_data = {
            "plus_button_selector": plus_selector,
            "import_option_selector": import_selector,
            "timestamp": time.time(),
            "confidence": "proven",  # Elevated from auto_created to proven
            "source": "validated_from_current_run",
            "version": "2.0",
            "integrity_hash": compute_cache_hash(plus_selector, import_selector),
            "platform": sys.platform,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "validated_at": datetime.now().isoformat()
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        # Update metadata - track successful validations
        metadata['validated_count'] = metadata.get('validated_count', 0) + 1
        metadata['last_validated'] = time.time()
        metadata['current_confidence'] = "proven"
        save_cache_metadata(profile_dir, metadata)
        
        jlog("behavior_cache_saved_validated",
             plus_selector=plus_selector[:50],
             import_selector=import_selector[:50],
             confidence="proven",
             level="INFO")
        
    except Exception as e:
        jlog("behavior_cache_save_error", error=str(e), 
             path=str(cache_path), level="WARN")

def invalidate_behavior_cache(profile_dir: Path):
    """Invalidate cache explicitly."""
    cache_path = profile_dir / UPLOAD_BEHAVIOR_CACHE_FILE
    metadata = load_cache_metadata(profile_dir)
    
    if cache_path.exists():
        try:
            cache_path.unlink()
            jlog("behavior_cache_invalidated", level="INFO")
        except Exception as e:
            jlog("behavior_cache_invalidate_error", error=str(e),
                 path=str(cache_path), level="WARN")
    
    # Mark invalidation in metadata
    metadata['invalidation_count'] = metadata.get('invalidation_count', 0) + 1
    metadata['last_invalidated'] = time.time()
    save_cache_metadata(profile_dir, metadata)