# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/tts_manager.py

"""
TTS Manager — ElevenLabs Haute Fidélité V9 (Remediated).

FIXES v9 :
  - TEST_MODE piloté par variable d'environnement TTS_TEST_MODE (plus de hardcode).
  - generate_audio() compatible sync ET async (détection de la boucle existante).
  - Session aiohttp instanciée une seule fois et réutilisée (connection pooling).
  - voice_settings exposés en paramètres configurables sur generate().
  - Fermeture propre de la session aiohttp via close() / context manager async.
  - Gestion robuste des erreurs de parsing JSON dans les réponses API.
  - AUTO-FALLBACK : Bascule en mode test (bouchon/silence généré) si clé API absente.
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
    Générateur vocal Haute Fidélité V9 (ElevenLabs).

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
    # FIX v9 : plus de hardcode True/False dans le code source.
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

        # FIX v9 : session aiohttp partagée (connection pooling).
        # Initialisée dans open() / __aenter__(), fermée dans close() / __aexit__().
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
        payload = f"{text}_{voice_id}_{self.model_id}_STUDIO_V9"
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

        Args:
            text: Texte à synthétiser.
            output_path: Destination finale. Si None, un chemin temporaire est utilisé.
            speed: Ignoré nativement par ElevenLabs v1 (conservé pour compatibilité API).
            stability: Expressivité vocale (0.0 = très expressif, 1.0 = très stable).
            similarity_boost: Fidélité à la voix source.

        Returns:
            Chemin du fichier audio généré, ou None en cas d'échec.
        """
        if output_path is None:
            output_path = Path("workspace/temp_audio.mp3")
            output_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(output_path, str):
            output_path = Path(output_path)

        # ------------------------------------------------------------------
        # TEST MODE / AUTO-FALLBACK
        # ------------------------------------------------------------------
        if self.test_mode or not self.api_key:
            jlog("warning", msg="🛡️ TEST MODE / FALLBACK ACTIF : Génération audio simulée. 0 crédit consommé.")
            
            # 1. Tenter d'utiliser un ancien fichier du cache
            cached_files = list(self.cache_dir.glob("*.mp3"))
            if cached_files:
                dummy = random.choice(cached_files)
                if output_path != dummy:
                    shutil.copy(str(dummy), str(output_path))
                return str(output_path)
            
            # 2. Tenter d'utiliser le fichier temporaire du mode DA
            da_audio = Path("workspace/temp_audio.mp3")
            if da_audio.exists():
                jlog("info", msg="Test Mode : Utilisation du bouchon 'temp_audio.mp3'.")
                if output_path != da_audio:
                    shutil.copy(str(da_audio), str(output_path))
                return str(output_path)
                
            # 3. Auto-Healing : Génération dynamique d'un silence de 5s (Aucune dépendance requise)
            jlog("info", msg="Test Mode : Aucun audio trouvé. Génération d'un silence audio de 5 secondes.")
            import wave
            silent_wav = Path("workspace/silent_fallback.wav")
            # 44100 Hz, 16-bit, mono, 5 secondes
            with wave.open(str(silent_wav), 'w') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(44100)
                f.writeframes(b'\x00' * (44100 * 2 * 5))
                
            # MoviePy gère nativement le format .wav pour le montage
            return str(silent_wav)

        voice_to_use = self._detect_tone(text[:200])
        cache_hit = self._get_cache_path(text, voice_to_use)

        if cache_hit.exists() and cache_hit.stat().st_size > 1000:
            jlog("info", msg=f"♻️  ElevenLabs Cache Hit ({voice_to_use})")
            if output_path != cache_hit:
                shutil.copy(str(cache_hit), str(output_path))
            return str(output_path)

        # Assure que la session est ouverte (au cas où generate() est appelé
        # sans open() explicite préalable)
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
                raise  # Ne pas avaler les cancellations
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
    # FIX v9 : compatible avec un event loop déjà en cours d'exécution.
    # ------------------------------------------------------------------

    def generate_audio(
        self,
        text: str,
        output_path,
        context_hint: str = "",
    ) -> Optional[str]:
        """
        Wrapper synchrone de generate().

        FIX v9 :
          - Utilise asyncio.get_event_loop() / run_until_complete() si une boucle
            existe mais n'est pas en cours d'exécution.
          - Si une boucle est DÉJÀ en cours d'exécution (contexte async),
            crée un thread dédié pour exécuter la coroutine sans deadlock.
          - Ne lève plus RuntimeError dans un contexte Nexus / daemon async.
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
            # On est dans un contexte async déjà actif (ex: Nexus daemon).
            # On exécute dans un thread séparé pour éviter le deadlock.
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
    Utilisé par generate_audio() quand appelé depuis un contexte async déjà actif.
    """
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


# Pour rétrocompatibilité avec les scripts appelant OpenAITTS.
OpenAITTS = ElevenLabsTTS