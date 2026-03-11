# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/tts_manager.py
import os
import hashlib
import shutil
import time
import asyncio
import random
from pathlib import Path
import sys
import aiohttp # Utilisé pour une connexion asynchrone ultra-stable à ElevenLabs

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import jlog, CONFIG

class ElevenLabsTTS:
    """
    Générateur vocal Haute Fidélité V8 (ElevenLabs B2B/Shorts Mode).
    Remplace OpenAI + Pedalboard. L'audio brut d'ElevenLabs est déjà masterisé
    et contient des micro-respirations humaines. Aucun post-processing requis.
    """
    
    # =========================================================================
    # 🛡️ BOUCLIER FINANCIER (TEST MODE)
    # Mettre à True pour tester la vidéo SANS payer de crédits ElevenLabs.
    # Il piochera un ancien audio aléatoire dans assets/cache/tts/.
    # Mettre à False quand le bot part en Production réelle.
    # =========================================================================
    TEST_MODE = True
    
    # Mapping des mots-clés avec POIDS (Weight) pour la détection heuristique
    # Format: "categorie": {"keywords": [(mot, poids)], "voice_id": ID ElevenLabs}
    VOICE_MAPPING = {
        "urgent": {
            # Adam : Voix profonde, grave, parfaite pour l'urgence, la motivation et l'impact
            "keywords": [("urgent", 5), ("alert", 5), ("crash", 5), ("danger", 4), ("stop", 3), ("vite", 3)],
            "voice_id": "pNInz6obpgDQGcFmaJgB" 
        },
        "b2b": {
            # Antoni : Voix jeune, dynamique, excellente pour les tutos B2B et l'acquisition
            "keywords": [("client", 5), ("business", 5), ("argent", 4), ("stratégie", 4), ("vente", 4), ("marketing", 3)],
            "voice_id": "ErXwobaYiN019PkySvjV"
        },
        "narrative": {
            # Marcus : Voix autoritaire, posée, excellente pour le storytelling
            "keywords": [("histoire", 4), ("story", 4), ("concept", 3), ("secret", 3)],
            "voice_id": "bVMeCyTHy58xNoL34h3p"
        },
        "calm": {
            # Fin : Voix claire, posée, didactique
            "keywords": [("tuto", 3), ("guide", 3), ("serein", 4), ("calme", 4), ("étape", 2), ("simple", 2)],
            "voice_id": "jBpfuIE2acCO8z3wKNLl"
        }
    }

    def __init__(self):
        # Récupération de la clé API ElevenLabs avec protection "Invalid Key"
        raw_key = CONFIG.get("api_keys", {}).get("elevenlabs", "")
        if not raw_key or "VOTRE_CLE" in raw_key or "YOUR_API_KEY" in raw_key:
            self.api_key = os.getenv("ELEVENLABS_API_KEY")
            # Ne log l'erreur que si on n'est PAS en mode test
            if not self.api_key and not self.TEST_MODE:
                jlog("error", msg="API Key ElevenLabs manquante ou invalide. Vérifiez config.yaml ou ELEVENLABS_API_KEY.")
        else:
            self.api_key = raw_key

        self.default_voice_id = "pNInz6obpgDQGcFmaJgB" # Adam par défaut (La voix la plus virale)
        self.model_id = "eleven_multilingual_v2" # Modèle V2 (Gère parfaitement le français)
        
        self.cache_dir = Path("assets/cache/tts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _detect_tone(self, text_snippet: str) -> str:
        """
        Détection de ton pondérée (Weighted Scoring) pour choisir la meilleure voix ElevenLabs.
        """
        text_lower = text_snippet.lower()
        scores = {k: 0 for k in self.VOICE_MAPPING.keys()}
        
        for category, config in self.VOICE_MAPPING.items():
            for kw, weight in config["keywords"]:
                if kw in text_lower:
                    scores[category] += weight
        
        best_cat = max(scores, key=scores.get)
        
        if scores[best_cat] == 0:
            return self.default_voice_id
            
        jlog("intelligence", msg="Ton détecté", tone=best_cat, score=scores[best_cat])
        return self.VOICE_MAPPING[best_cat]["voice_id"]

    def _get_cache_path(self, text: str, voice_id: str) -> Path:
        # Hachage pour éviter de repayer des requêtes identiques (Économie de crédits)
        payload = f"{text}_{voice_id}_{self.model_id}_STUDIO_V8" 
        file_hash = hashlib.md5(payload.encode('utf-8')).hexdigest()
        return self.cache_dir / f"{file_hash}.mp3" 

    async def generate(self, text: str, output_path: Path = None, speed: float = 1.0) -> str:
        """
        Génère l'audio via ElevenLabs avec système de Cache et Résilience (Retry).
        Note: Le paramètre `speed` n'est pas utilisé nativement par ElevenLabs v1, 
        la dynamique de la voix s'auto-régule avec l'IA.
        """
        if not output_path:
            output_path = Path("workspace/temp_audio.mp3") 
            output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(output_path, str): output_path = Path(output_path)

        # ---------------------------------------------------------------------
        # COUPE-CIRCUIT : MODE TEST (0 CRÉDIT)
        # ---------------------------------------------------------------------
        if self.TEST_MODE:
            jlog("warning", msg="🛡️ TEST MODE ACTIF : Utilisation d'un audio en cache. 0 crédit dépensé.")
            cached_files = list(self.cache_dir.glob("*.mp3"))
            if cached_files:
                # Prend un audio au hasard dans tes anciens tests
                dummy_audio = random.choice(cached_files)
                shutil.copy(str(dummy_audio), str(output_path))
                return str(output_path)
            else:
                jlog("error", msg="Aucun ancien audio trouvé dans le cache pour le Mode Test. L'assemblage vidéo va échouer.")
                return None
        # ---------------------------------------------------------------------

        if not self.api_key: 
            jlog("error", msg="Impossible de générer : API Key ElevenLabs manquante.")
            return None

        try:
            # 1. Intelligence : Choix du Voice ID
            voice_to_use = self._detect_tone(text[:200])
            
            # 2. Vérification Cache (Crucial pour ElevenLabs pour ne pas brûler les crédits)
            cache_hit = self._get_cache_path(text, voice_to_use)
            if cache_hit.exists() and cache_hit.stat().st_size > 1000:
                jlog("info", msg=f"♻️  ElevenLabs Cache Hit ({voice_to_use})")
                shutil.copy(str(cache_hit), str(output_path))
                return str(output_path)

            # 3. Appel API avec Résilience (Exponential Backoff) ASYNCHRONE
            max_retries = 3
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_to_use}"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key
            }
            
            # Paramètres Premium ElevenLabs
            data = {
                "text": text,
                "model_id": self.model_id,
                "voice_settings": {
                    "stability": 0.45,       # Plus c'est bas, plus c'est expressif et humain (0.45 = idéal Shorts)
                    "similarity_boost": 0.75 # Garde la signature vocale forte
                }
            }

            async with aiohttp.ClientSession() as session:
                for attempt in range(max_retries):
                    try:
                        jlog("debug", msg=f"Génération ElevenLabs... Tentative {attempt+1}/{max_retries}")
                        
                        async with session.post(url, json=data, headers=headers, timeout=30) as response:
                            if response.status == 200:
                                # Écriture du fichier binaire directement dans le cache
                                with open(cache_hit, 'wb') as f:
                                    async for chunk in response.content.iter_chunked(1024):
                                        if chunk: f.write(chunk)
                                break # Succès, on sort de la boucle
                            else:
                                err_text = await response.text()
                                raise Exception(f"HTTP {response.status}: {err_text}")
                            
                    except Exception as e:
                        jlog("warning", msg=f"Erreur API ElevenLabs (Tentative {attempt+1})", error=str(e))
                        if attempt < max_retries - 1:
                            sleep_time = 2 ** (attempt + 1)
                            # Remplacement du time.sleep par await asyncio.sleep pour ne pas bloquer le daemon
                            await asyncio.sleep(sleep_time)
                        else:
                            raise e 
            
            # 4. Copie vers destination finale
            jlog("success", msg="✨ Audio ElevenLabs généré avec succès")
            if output_path != cache_hit:
                shutil.copy(str(cache_hit), str(output_path))
            
            return str(output_path)

        except Exception as e:
            jlog("error", msg="Erreur critique TTS ElevenLabs après retries", error=str(e))
            return None
    
    # Alias de compatibilité absolue pour les autres scripts
    def generate_audio(self, text, output_path, context_hint=""):
        return asyncio.run(self.generate(text, output_path))

# Pour rétrocompatibilité avec les scripts appelant OpenAITTS, on redirige la classe.
# C'est la garantie Zéro Régression de l'orchestrateur.
OpenAITTS = ElevenLabsTTS