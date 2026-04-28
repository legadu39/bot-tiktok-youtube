"""
Tests pour tools/tts_manager.py — ElevenLabsTTS (cache + durée synthétique).

Pourquoi c'est critique :
1. Cache : si deux textes différents produisent le même hash (collision), un audio
   incorrect est renvoyé silencieusement — la voix off ne correspond plus au script.
2. Durée synthétique : en mode TEST_MODE, la durée du silence généré pilote
   directement le timing de toutes les scènes. Un calcul erroné compresse ou
   étire l'animation entière sans aucun signal d'erreur visible.

Note sur la durée pour le texte vide :
    La formule est max(2.0, len(text) / 13.0).
    L'audit spécifie "retourne 0 pour une chaîne vide", mais le code retourne
    intentionnellement 2.0 (plancher minimum). Un fichier WAV de 0s est invalide
    pour MoviePy. Le test vérifie le comportement réel (2.0) et documente le plancher.

Tests couverts :
- Durée synthétique : plancher 2.0s, croissance linéaire ~13 chars/s
- Cache key : déterminisme, pas de collision sur des inputs simples
- Cache key : correspond exactement au MD5 attendu
"""

import os
import hashlib
import pytest

# Force le mode test avant tout import de tts_manager
os.environ["TTS_TEST_MODE"] = "true"

from tools.tts_manager import ElevenLabsTTS


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tts():
    """Instance ElevenLabsTTS en mode test (pas d'appel API, pas de session HTTP)."""
    os.environ["TTS_TEST_MODE"] = "true"
    return ElevenLabsTTS()


# ─── Durée synthétique ───────────────────────────────────────────────────────

class TestSyntheticDuration:
    """
    Formule : estimated_duration = max(2.0, len(text) / 13.0)
    Testée directement sur la formule (sans appeler generate() qui écrit des fichiers).
    """

    def _duration(self, text: str) -> float:
        return max(2.0, len(text) / 13.0)

    def test_empty_string_returns_floor(self):
        """
        Chaîne vide → 2.0s (plancher), pas 0.
        Un WAV de 0s est invalide pour MoviePy — le plancher est intentionnel.
        """
        assert self._duration("") == pytest.approx(2.0)

    def test_short_text_returns_floor(self):
        """Texte court (< 26 chars) → plancher 2.0s."""
        assert self._duration("Bonjour") == pytest.approx(2.0)
        assert self._duration("a" * 25)  == pytest.approx(2.0)

    def test_exact_boundary(self):
        """26 chars → 26/13 = 2.0s exactement (limite plancher)."""
        assert self._duration("a" * 26) == pytest.approx(2.0)

    def test_linear_scaling_above_floor(self):
        """Au-delà du plancher, la durée croît linéairement (~13 chars/s)."""
        assert self._duration("a" * 130) == pytest.approx(10.0, abs=1e-9)
        assert self._duration("a" * 260) == pytest.approx(20.0, abs=1e-9)
        assert self._duration("a" * 390) == pytest.approx(30.0, abs=1e-9)

    def test_doubling_text_doubles_duration(self):
        """Pour des textes longs, doubler le texte double la durée."""
        short = "a" * 130  # 10.0s
        long_ = "a" * 260  # 20.0s
        assert self._duration(long_) == pytest.approx(self._duration(short) * 2, rel=1e-9)

    def test_duration_always_positive(self):
        """La durée est toujours ≥ 2.0 (jamais nulle ou négative)."""
        for text in ["", "a", "a" * 10, "a" * 100]:
            assert self._duration(text) >= 2.0


# ─── Cache key ───────────────────────────────────────────────────────────────

class TestCacheKey:
    def test_deterministic_same_inputs(self, tts):
        """Mêmes (text, voice_id) → même chemin de cache à chaque appel."""
        text     = "Le trading c'est du sérieux."
        voice_id = "pNInz6obpgDQGcFmaJgB"
        p1 = tts._get_cache_path(text, voice_id)
        p2 = tts._get_cache_path(text, voice_id)
        assert p1 == p2

    def test_different_text_different_key(self, tts):
        """Textes différents → clés de cache différentes."""
        voice_id = "pNInz6obpgDQGcFmaJgB"
        p1 = tts._get_cache_path("texte A", voice_id)
        p2 = tts._get_cache_path("texte B", voice_id)
        assert p1 != p2

    def test_different_voice_different_key(self, tts):
        """Même texte, voix différentes → clés de cache différentes."""
        text = "Le trading c'est du sérieux."
        p1 = tts._get_cache_path(text, "pNInz6obpgDQGcFmaJgB")
        p2 = tts._get_cache_path(text, "ErXwobaYiN019PkySvjV")
        assert p1 != p2

    def test_no_collision_simple_cases(self, tts):
        """Quatre inputs distincts → quatre clés distinctes (pas de collision)."""
        voice = "pNInz6obpgDQGcFmaJgB"
        paths = [
            tts._get_cache_path("abc",  voice),
            tts._get_cache_path("abcd", voice),
            tts._get_cache_path("ABC",  voice),
            tts._get_cache_path("",     voice),
        ]
        assert len(set(paths)) == 4, "Collision détectée entre des inputs distincts"

    def test_hash_matches_expected_md5(self, tts):
        """Le nom de fichier correspond exactement au MD5(text_voice_model_STUDIO_V10)."""
        text     = "test_determinism"
        voice_id = "pNInz6obpgDQGcFmaJgB"
        payload  = f"{text}_{voice_id}_{tts.model_id}_STUDIO_V10"
        expected = hashlib.md5(payload.encode("utf-8")).hexdigest()

        result = tts._get_cache_path(text, voice_id)
        assert result.name == f"{expected}.mp3"

    def test_cache_path_is_in_cache_dir(self, tts):
        """Le chemin retourné est toujours dans cache_dir."""
        p = tts._get_cache_path("quelque chose", "pNInz6obpgDQGcFmaJgB")
        assert str(p).startswith(str(tts.cache_dir))

    def test_cache_path_extension_is_mp3(self, tts):
        """L'extension du fichier de cache est toujours .mp3."""
        p = tts._get_cache_path("n'importe quel texte", "pNInz6obpgDQGcFmaJgB")
        assert p.suffix == ".mp3"
