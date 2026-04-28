"""
Tests pour common.py — CircuitBreaker et VideoValidator.

Pourquoi c'est critique :
- CircuitBreaker protège le pipeline contre les appels répétés à un service
  défaillant (Gemini, ElevenLabs). S'il ne s'ouvre pas après 3 échecs,
  le daemon spamme l'API jusqu'au bannissement ou à l'épuisement du quota.
  S'il ne se réinitialise pas après le timeout, le pipeline reste bloqué indéfiniment.
- VideoValidator est le gardien Fail-Fast avant chaque upload. Une fausse validation
  (retourne True sur une vidéo invalide) soumet un fichier inutilisable à TikTok/YouTube
  — l'uploader échoue ensuite silencieusement avec une erreur opaque.

Tests couverts :
- CircuitBreaker : ouverture après max_failures échecs consécutifs
- CircuitBreaker : transition OPEN → HALF_OPEN après le timeout
- CircuitBreaker : record_success réinitialise le compteur et ferme le circuit
- VideoValidator : rejet fichier inexistant
- VideoValidator : rejet vidéo paysage (width > height)
"""

import time
import pytest
from unittest.mock import patch

from common import CircuitBreaker, VideoValidator


# ─── CircuitBreaker ───────────────────────────────────────────────────────────

class TestCircuitBreaker:

    def _make_cb(self, max_failures: int = 3, reset_timeout: int = 1800) -> CircuitBreaker:
        """Crée un CircuitBreaker avec des paramètres explicites (ignore CONFIG)."""
        cb = CircuitBreaker("test_service")
        cb.max_failures  = max_failures
        cb.reset_timeout = reset_timeout
        return cb

    def test_initial_state_is_closed(self):
        """Le circuit démarre fermé (disponible)."""
        cb = self._make_cb()
        assert cb.state == "CLOSED"
        assert cb.is_available()

    def test_opens_after_max_failures(self):
        """Après max_failures échecs consécutifs, le circuit s'ouvre."""
        cb = self._make_cb(max_failures=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert not cb.is_available()

    def test_does_not_open_before_max_failures(self):
        """Sous le seuil, le circuit reste fermé."""
        cb = self._make_cb(max_failures=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "CLOSED"
        assert cb.is_available()

    def test_half_open_after_timeout(self):
        """Après reset_timeout secondes, OPEN → HALF_OPEN et is_available() == True."""
        cb = self._make_cb(max_failures=3, reset_timeout=10)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"
        assert not cb.is_available()

        # Simule l'écoulement du temps en antidatant last_failure_time
        cb.last_failure_time = time.time() - 11  # 11s > reset_timeout=10s

        assert cb.is_available()
        assert cb.state == "HALF_OPEN"

    def test_success_resets_counter(self):
        """record_success remet failure_count à 0 et ferme le circuit."""
        cb = self._make_cb(max_failures=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"

    def test_success_after_open_closes(self):
        """record_success depuis OPEN referme le circuit."""
        cb = self._make_cb(max_failures=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "OPEN"

        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.is_available()

    def test_failure_count_increments(self):
        """record_failure incrémente failure_count à chaque appel."""
        cb = self._make_cb(max_failures=10)
        for i in range(1, 6):
            cb.record_failure()
            assert cb.failure_count == i

    def test_open_circuit_unavailable_before_timeout(self):
        """Circuit ouvert reste indisponible tant que le timeout n'est pas écoulé."""
        cb = self._make_cb(max_failures=3, reset_timeout=3600)
        for _ in range(3):
            cb.record_failure()

        # last_failure_time = now → timeout non écoulé
        cb.last_failure_time = time.time()
        assert not cb.is_available()


# ─── VideoValidator ───────────────────────────────────────────────────────────

class TestVideoValidator:

    def _mock_check_output(self, width: int, height: int, duration: float = 30.0):
        """
        Retourne un side_effect pour subprocess.check_output simulant
        deux appels ffprobe distincts (dimensions puis durée).
        """
        def side_effect(cmd, **kwargs):
            # Détecte l'appel dimension vs durée par le contenu de la commande
            cmd_str = " ".join(str(c) for c in cmd)
            if "width,height" in cmd_str:
                return f"{width}\n{height}\n".encode()
            else:
                return f"{duration}\n".encode()
        return side_effect

    def test_rejects_nonexistent_file(self):
        """Fichier absent → False immédiat, sans appel ffprobe."""
        ok, reason = VideoValidator.validate_for_platform("/chemin/qui/nexiste/pas.mp4")
        assert not ok
        assert "introuvable" in reason.lower()

    def test_rejects_landscape_video(self, tmp_path):
        """Vidéo paysage (width > height) → rejetée avec message explicite."""
        dummy = tmp_path / "landscape.mp4"
        dummy.write_bytes(b"\x00" * 100)  # fichier factice qui existe

        with patch("common.subprocess.check_output",
                   side_effect=self._mock_check_output(width=1920, height=1080)):
            ok, reason = VideoValidator.validate_for_platform(str(dummy))

        assert not ok
        assert "Paysage" in reason

    def test_accepts_vertical_video(self, tmp_path):
        """Vidéo verticale (width < height) → acceptée."""
        dummy = tmp_path / "vertical.mp4"
        dummy.write_bytes(b"\x00" * 100)

        with patch("common.subprocess.check_output",
                   side_effect=self._mock_check_output(width=1080, height=1920,
                                                        duration=45.0)):
            ok, reason = VideoValidator.validate_for_platform(str(dummy))

        assert ok, f"Vidéo verticale rejetée à tort : {reason}"

    def test_rejects_too_long_video(self, tmp_path):
        """Vidéo dépassant max_duration + 2s → rejetée."""
        dummy = tmp_path / "too_long.mp4"
        dummy.write_bytes(b"\x00" * 100)

        with patch("common.subprocess.check_output",
                   side_effect=self._mock_check_output(width=1080, height=1920,
                                                        duration=65.0)):  # max=60+2=62
            ok, reason = VideoValidator.validate_for_platform(str(dummy))

        assert not ok
        assert "Durée" in reason or "longue" in reason.lower()

    def test_square_video_not_landscape(self, tmp_path):
        """Vidéo carrée (width == height) n'est pas rejetée comme paysage."""
        dummy = tmp_path / "square.mp4"
        dummy.write_bytes(b"\x00" * 100)

        with patch("common.subprocess.check_output",
                   side_effect=self._mock_check_output(width=1080, height=1080,
                                                        duration=30.0)):
            ok, reason = VideoValidator.validate_for_platform(str(dummy))

        # width > height est strict → carré n'est pas rejeté pour cette raison
        assert "Paysage" not in reason

    def test_ffprobe_timeout_returns_bypass(self, tmp_path):
        """Timeout ffprobe → bypass silencieux (True) pour ne pas bloquer le pipeline."""
        import subprocess
        dummy = tmp_path / "timeout.mp4"
        dummy.write_bytes(b"\x00" * 100)

        with patch("common.subprocess.check_output",
                   side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=10)):
            ok, reason = VideoValidator.validate_for_platform(str(dummy))

        assert ok  # bypass intentionnel
        assert "Timeout" in reason
