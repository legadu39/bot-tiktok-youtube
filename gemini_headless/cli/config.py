# gemini_headless/cli/config.py
import os
from typing import Dict, Any

# ============================================================================
# TIMEOUT CONFIGURATION (SMART V3)
# ============================================================================

DEFAULT_TIMEOUT_CONFIG = {
    "heartbeat_timeout_s": 120.0,
    "generation_timeout_s": 480.0,
    "activity_probe_s": 15.0
}

MODEL_TIMEOUT_CONFIGS = {
    "gemini-1.5-flash": {
        "heartbeat_timeout_s": 120.0,
        "generation_timeout_s": 300.0,
    },
    "gemini-1.5-pro": {
        "heartbeat_timeout_s": 180.0,
        "generation_timeout_s": 600.0,
    }
}

def predict_complexity(prompt: str) -> Dict[str, Any]:
    """
    Analyse le prompt pour deviner l'intention et la complexité.
    Retourne un profil de configuration.
    """
    if not prompt:
        return {"level": "normal", "visual": False}
        
    p = prompt.lower()
    
    # 1. Détection Visuelle
    visual_keywords = ["image", "photo", "dessin", "picture", "draw", "generate image", "illustration"]
    is_visual = any(k in p for k in visual_keywords)
    
    # 2. Détection Complexité
    complexity_score = 0
    complexity_score += len(p) / 1000  # +1 point par 1000 chars
    
    heavy_keywords = ["code", "script", "analyse", "tableau", "excel", "summary", "report", "essay", "article"]
    if any(k in p for k in heavy_keywords):
        complexity_score += 2
        
    level = "normal"
    if complexity_score > 3: level = "high"
    elif complexity_score < 0.2 and len(p) < 50: level = "low" # Ping
    
    return {
        "level": level,
        "visual": is_visual,
        "score": complexity_score
    }

def calculate_adaptive_timeouts(model_name: str = "gemini-1.5-flash", video_size_mb: float = None, prompt: str = None) -> Dict[str, float]:
    """
    Calcule les timeouts optimaux en fonction du modèle, du fichier et du prompt.
    """
    # 1. Base Model Config
    base = MODEL_TIMEOUT_CONFIGS.get(model_name, DEFAULT_TIMEOUT_CONFIG).copy()
    
    # 2. Prompt Complexity Analysis
    analysis = predict_complexity(prompt)
    
    # Ajustement basé sur l'intention visuelle
    if analysis["visual"]:
        # Les images prennent du temps et ont une pause silencieuse
        base["generation_timeout_s"] = max(base["generation_timeout_s"], 600.0)
        # On augmente le heartbeat car le modèle "réfléchit" visuellement sans envoyer de texte
        base["heartbeat_timeout_s"] = max(base["heartbeat_timeout_s"], 200.0)
        
    # Ajustement basé sur la complexité textuelle
    elif analysis["level"] == "high":
        base["generation_timeout_s"] *= 1.5
    elif analysis["level"] == "low":
        # Fail-fast pour les requêtes simples
        base["generation_timeout_s"] = 60.0

    # 3. File Upload Impact
    if video_size_mb:
        # +10s par MB (upload + processing)
        extra_time = video_size_mb * 10.0
        base["generation_timeout_s"] += extra_time
        # Upload time needs lenient heartbeat
        base["heartbeat_timeout_s"] = max(base["heartbeat_timeout_s"], 300.0)

    # 4. Environment Overrides
    try:
        if os.getenv("GH_TIMEOUT_GEN"):
            base["generation_timeout_s"] = float(os.getenv("GH_TIMEOUT_GEN"))
        if os.getenv("GH_TIMEOUT_HB"):
            base["heartbeat_timeout_s"] = float(os.getenv("GH_TIMEOUT_HB"))
    except: pass

    # Sécurité: bornes minimales
    base["generation_timeout_s"] = max(30.0, base["generation_timeout_s"])
    base["heartbeat_timeout_s"] = max(60.0, base["heartbeat_timeout_s"])
    
    # Ajout des métadonnées d'analyse pour le CLI
    base["_analysis"] = analysis

    return base