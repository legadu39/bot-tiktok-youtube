# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/tts_manager.py

"""
TTS Manager — ElevenLabs Haute Fidélité V10 (Synchronisation Mathématique).

FIXES v10 :
  - AUTO-FALLBACK DYNAMIQUE : Le mode test ne pioche plus de vieux audios au hasard.
    Il lit le texte, calcule le temps humain nécessaire (~13 chars/s) et génère
    un fichier .wav silencieux millimétré pour garantir un pacing vidéo parfait.
FIXES v9 :
  - TEST_MODE piloté par variable d'environnement TTS_TEST_MODE.
  - generate_audio() compatible sync ET async (détection de la boucle existante).
  - Session aiohttp instanciée une seule fois et réutilisée (connection pooling).
  - voice_settings exposés en paramètres configurables sur generate().
  - Fermeture propre de la session aiohttp via close() / context manager async.
"""

import os
import hashlib
import shutil
import time
import asyncio
import random
import logging
from pathlib import Path
import sys
from typing import Optional

import aiohttp

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import jlog, CONFIG

logger = logging.getLogger("TTS_Manager")


class ElevenLabsTTS:
    """
    Générateur vocal Haute Fidélité V10 (ElevenLabs).

    Utilisation recommandée :
        # Contexte async
        tts = ElevenLabsTTS()
        await tts.open()
        path = await tts.generate("Mon texte")
        await tts.close()

        # Ou avec context manager async
        async with ElevenLabsTTS() as tts:
            path = await tts.generate("Mon texte")

        # Contexte synchrone (depuis un thread non-async)
        tts = ElevenLabsTTS()
        path = tts.generate_audio("Mon texte", Path("out.mp3"))
    """

    # =========================================================================
    # TEST MODE — piloté par variable d'environnement
    # Mettre TTS_TEST_MODE=true dans l'environnement pour activer.
    # =========================================================================
    @staticmethod
    def _resolve_test_mode() -> bool:
        val = os.getenv("TTS_TEST_MODE", "false").strip().lower()
        return val in ("1", "true", "yes", "on")

    VOICE_MAPPING = {
        "urgent": {
            "keywords": [("urgent", 5), ("alert", 5), ("crash", 5), ("danger", 4), ("stop", 3), ("vite", 3)],
            "voice_id": "pNInz6obpgDQGcFmaJgB",
        },
        "b2b": {
            "keywords": [("client", 5), ("business", 5), ("argent", 4), ("stratégie", 4), ("vente", 4), ("marketing", 3)],
            "voice_id": "ErXwobaYiN019PkySvjV",
        },
        "narrative": {
            "keywords": [("histoire", 4), ("story", 4), ("concept", 3), ("secret", 3)],
            "voice_id": "bVMeCyTHy58xNoL34h3p",
        },
        "calm": {
            "keywords": [("tuto", 3), ("guide", 3), ("serein", 4), ("calme", 4), ("étape", 2), ("simple", 2)],
            "voice_id": "jBpfuIE2acCO8z3wKNLl",
        },
    }

    def __init__(self):
        self.test_mode: bool = self._resolve_test_mode()

        raw_key = CONFIG.get("api_keys", {}).get("elevenlabs", "")
        if not raw_key or "VOTRE_CLE" in raw_key or "YOUR_API_KEY" in raw_key:
            self.api_key: Optional[str] = os.getenv("ELEVENLABS_API_KEY")
            if not self.api_key and not self.test_mode:
                jlog("warning", msg="API Key ElevenLabs manquante. Activation automatique du mode TEST/FALLBACK.")
                self.test_mode = True
        else:
            self.api_key = raw_key

        self.default_voice_id = "pNInz6obpgDQGcFmaJgB"
        self.model_id = "eleven_multilingual_v2"

        self.cache_dir = Path("assets/cache/tts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Context manager async
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ElevenLabsTTS":
        await self.open()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def open(self):
        """Ouvre la session HTTP poolée. Idempotent."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(limit=4, ttl_dns_cache=300)
                timeout = aiohttp.ClientTimeout(total=45, connect=10)
                self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    async def close(self):
        """Ferme proprement la session HTTP."""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    # ------------------------------------------------------------------
    # Heuristiques internes
    # ------------------------------------------------------------------

    def _detect_tone(self, text_snippet: str) -> str:
        text_lower = text_snippet.lower()
        scores = {k: 0 for k in self.VOICE_MAPPING}
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
        payload = f"{text}_{voice_id}_{self.model_id}_STUDIO_V10"
        file_hash = hashlib.md5(payload.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{file_hash}.mp3"

    # ------------------------------------------------------------------
    # Génération principale (async)
    # ------------------------------------------------------------------

    async def generate(
        self,
        text: str,
        output_path: Optional[Path] = None,
        speed: float = 1.0,
        stability: float = 0.45,
        similarity_boost: float = 0.75,
    ) -> Optional[str]:
        """
        Génère l'audio via ElevenLabs avec cache et résilience.
        """
        if output_path is None:
            output_path = Path("workspace/temp_audio.mp3")
            output_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(output_path, str):
            output_path = Path(output_path)

        # ------------------------------------------------------------------
        # TEST MODE / AUTO-FALLBACK V10 (Synchronisation Mathématique)
        # ------------------------------------------------------------------
        if self.test_mode or not self.api_key:
            jlog("warning", msg="🛡️ TEST MODE / FALLBACK ACTIF : Génération d'un faux audio synchronisé au texte réel.")
            
            # Calcul de la durée exacte nécessaire pour le VRAI TEXTE de cette session.
            # Vitesse de lecture moyenne : ~13 caractères par seconde.
            estimated_duration = max(2.0, len(text) / 13.0)
            
            import wave
            # On force le format .wav pour le silence synthétique
            silent_wav = output_path.with_suffix(".wav")
            
            framerate = 44100
            num_frames = int(framerate * estimated_duration)
            
            # Génération d'un silence absolu de la durée EXACTE du script texte
            with wave.open(str(silent_wav), 'w') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(framerate)
                f.writeframes(b'\x00' * (num_frames * 2))
                
            jlog("info", msg=f"Silence synthétique généré : {estimated_duration:.2f}s pour {len(text)} caractères.")
            
            return str(silent_wav)

        voice_to_use = self._detect_tone(text[:200])
        cache_hit = self._get_cache_path(text, voice_to_use)

        if cache_hit.exists() and cache_hit.stat().st_size > 1000:
            jlog("info", msg=f"♻️  ElevenLabs Cache Hit ({voice_to_use})")
            if output_path != cache_hit:
                shutil.copy(str(cache_hit), str(output_path))
            return str(output_path)

        await self.open()

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_to_use}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key,
        }
        data = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                jlog("debug", msg=f"Génération ElevenLabs... Tentative {attempt + 1}/{max_retries}")
                async with self._session.post(url, json=data, headers=headers) as response:
                    if response.status == 200:
                        with open(cache_hit, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                if chunk:
                                    f.write(chunk)
                        break
                    else:
                        err_text = await response.text()
                        raise aiohttp.ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=err_text,
                        )
            except asyncio.CancelledError:
                raise 
            except Exception as e:
                jlog("warning", msg=f"Erreur API ElevenLabs (tentative {attempt + 1})", error=str(e))
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                else:
                    jlog("error", msg="Erreur critique TTS après tous les retries.", error=str(e))
                    return None

        if not cache_hit.exists() or cache_hit.stat().st_size == 0:
            jlog("error", msg="Fichier audio vide après génération.")
            return None

        jlog("success", msg="✨ Audio ElevenLabs généré avec succès.")
        if output_path != cache_hit:
            shutil.copy(str(cache_hit), str(output_path))
        return str(output_path)

    # ------------------------------------------------------------------
    # generate_audio — alias sync (rétrocompatibilité totale)
    # ------------------------------------------------------------------

    def generate_audio(
        self,
        text: str,
        output_path,
        context_hint: str = "",
    ) -> Optional[str]:
        """
        Wrapper synchrone de generate().
        """
        if isinstance(output_path, str):
            output_path = Path(output_path)

        coro = self.generate(text, output_path)

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_coroutine_in_new_loop, coro)
                try:
                    return future.result(timeout=60)
                except concurrent.futures.TimeoutError:
                    jlog("error", msg="generate_audio timeout (thread isolé)")
                    return None
                except Exception as e:
                    jlog("error", msg="generate_audio erreur thread isolé", error=str(e))
                    return None
        else:
            return loop.run_until_complete(coro)


def _run_coroutine_in_new_loop(coro):
    """
    Exécute une coroutine dans une nouvelle boucle d'événements isolée.
    """
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


# Pour rétrocompatibilité avec les scripts appelant OpenAITTS.
OpenAITTS = ElevenLabsTTS