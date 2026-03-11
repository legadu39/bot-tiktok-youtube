# -*- coding: utf-8 -*-
### bot tiktok youtube/fallback.py
import random
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List

# Core configuration import
try:
    from common import jlog, resolve_path
except ImportError:
    def jlog(*args, **kwargs): print(kwargs.get("msg"))
    def resolve_path(p): return Path(p)

class FallbackProvider:
    """
    Système de secours (Hardcoded Intelligence).
    Intervient quand le Cerveau ou le CLI échoue.
    Garantit que le pipeline ne s'arrête JAMAIS.
    """
    def __init__(self):
        self.assets_dir = resolve_path("assets/placeholders")
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def get_placeholder_image(self) -> str:
        """Retourne une image locale de secours."""
        images = list(self.assets_dir.glob("*.jpg")) + list(self.assets_dir.glob("*.png"))
        if images:
            return str(random.choice(images))
        # Image noire générée si vide (Fallback du Fallback)
        return "" 

    async def generate_text(self, prompt: str) -> str:
        """Simulation d'IA pour les cas désespérés (utilisé par CLI en mode failover)."""
        jlog("fallback", msg="Generating synthetic response via FallbackProvider")
        await asyncio.sleep(1) # Simulation latence
        
        # Réponse générique mais valide
        return (
            "Voici une réponse générée par le système de secours car l'IA principale est indisponible. "
            "Le trading est une activité risquée qui nécessite discipline et stratégie. "
            "Les Prop Firms offrent du capital mais ont des règles strictes."
        )

    def generate_script(self, topic: str) -> Dict[str, Any]:
        """
        Génère un script JSON valide sans appel API.
        CRITIQUE : Empêche le crash 'AttributeError' dans NexusBrain.
        """
        jlog("fallback", msg=f"Generating EMERGENCY script for: {topic}")
        
        # Templates rotatifs pour varier même en mode panne
        templates = [
            {
                "hook": "Tu perds de l'argent en Trading ?",
                "body": "C'est normal. 90% échouent. La raison ? La psychologie. Arrête de chercher la stratégie miracle.",
                "cta": "Abonne-toi pour la vérité."
            },
            {
                "hook": "Le secret des Prop Firms dévoilé.",
                "body": "Elles ne veulent pas que tu gagnes. Le drawdown est ton ennemi. Maîtrise ton risque avant tout.",
                "cta": "Lien en bio pour apprendre."
            }
        ]
        
        chosen = random.choice(templates)
        
        return {
            "meta": {
                "title": f"{topic} #Shorts",
                "description": "Conseil Trading essentiel.",
                "tags": ["trading", "finance", "mindset"],
                "tts_speed": 1.1
            },
            "scenes": [
                {
                    "id": 1,
                    "text": chosen["hook"],
                    "visual_prompt": "angry trader looking at screens dark atmosphere",
                    "keywords": ["trader", "chart", "red"]
                },
                {
                    "id": 2,
                    "text": chosen["body"],
                    "visual_prompt": "stock market chart going down crash",
                    "keywords": ["graph", "money"]
                },
                {
                    "id": 3,
                    "text": chosen["cta"],
                    "visual_prompt": "successful businessman smiling luxury",
                    "keywords": ["success", "money"]
                }
            ]
        }