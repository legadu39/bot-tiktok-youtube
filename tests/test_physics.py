"""
Tests pour tools/physics.py — SpringPhysics et SpringLUT.

Pourquoi c'est critique : SpringPhysics est le moteur de toutes les animations
du pipeline (entrée des mots, scale, alpha, slide). Une régression dans les formules
analytiques produit des frames corrompues silencieusement — les valeurs numériques
incorrectes ne lèvent aucune exception mais détruisent l'effet visuel.

Tests couverts :
- Position initiale exacte (t=0 → 0.0)
- Convergence vers la cible (t→∞ → 1.0) dans les trois régimes d'amortissement
- Distinction des régimes : sous-amorti overshoot, critique/sur-amorti sans overshoot
- Validation des paramètres invalides (stiffness ≤ 0, damping < 0)
- SpringLUT : cohérence avec SpringPhysics analytique
"""

import math
import pytest
from tools.physics import SpringPhysics, SpringLUT


# ─── Valeur initiale ──────────────────────────────────────────────────────────

class TestValueAtZero:
    def test_underdamped(self):
        """Spring sous-amorti démarre exactement à 0."""
        sp = SpringPhysics(stiffness=900, damping=30)  # ζ=0.5
        assert sp.value(0.0) == pytest.approx(0.0, abs=1e-9)

    def test_critically_damped(self):
        """Spring critique démarre exactement à 0."""
        sp = SpringPhysics(stiffness=900, damping=60)  # ζ=1.0
        assert sp.value(0.0) == pytest.approx(0.0, abs=1e-9)

    def test_overdamped(self):
        """Spring sur-amorti démarre exactement à 0."""
        sp = SpringPhysics(stiffness=900, damping=120)  # ζ=2.0
        assert sp.value(0.0) == pytest.approx(0.0, abs=1e-9)

    def test_clamped_at_zero(self):
        """clamped(0) == 0 dans tous les régimes."""
        for k, c in [(900, 30), (900, 60), (900, 120)]:
            sp = SpringPhysics(stiffness=k, damping=c)
            assert sp.clamped(0.0) == pytest.approx(0.0, abs=1e-9)


# ─── Convergence vers 1.0 ────────────────────────────────────────────────────

class TestConvergence:
    """
    À t=5s, l'enveloppe exp(-ζω₀t) est négligeable pour tous les presets
    calibrés (settle 98% < 350ms). On tolère ±0.01.
    """

    @pytest.mark.parametrize("k,c,label", [
        (900,  30,  "underdamped ζ=0.50"),
        (900,  60,  "critical ζ=1.00"),
        (900,  120, "overdamped ζ=2.00"),
        (400,  20,  "slow underdamped"),
        (2000, 100, "ultra-snap"),
    ])
    def test_converges_to_one(self, k, c, label):
        sp = SpringPhysics(stiffness=k, damping=c)
        assert sp.value(5.0) == pytest.approx(1.0, abs=0.01), (
            f"{label}: value(5s) = {sp.value(5.0):.6f}, attendu ≈ 1.0"
        )


# ─── Régimes d'amortissement distincts ───────────────────────────────────────

class TestDampingRegimes:
    def test_underdamped_overshoots(self):
        """Sous-amorti (ζ<1) dépasse 1.0 — overshoot +15% pour ζ=0.5."""
        sp = SpringPhysics(stiffness=900, damping=30)  # ζ=0.5
        peak = max(sp.value(i / 1000) for i in range(1, 600))
        assert peak > 1.0, f"Spring sous-amorti devrait dépasser 1.0, pic={peak:.4f}"
        # On vérifie que l'overshoot est raisonnable (entre +5% et +30%)
        assert 1.05 < peak < 1.30

    def test_critical_does_not_overshoot(self):
        """Critique (ζ=1.0) ne dépasse pas 1.0."""
        sp = SpringPhysics(stiffness=900, damping=60)  # ζ=1.0
        peak = max(sp.value(i / 1000) for i in range(1, 600))
        assert peak <= 1.0 + 1e-6, f"Spring critique ne devrait pas dépasser 1.0, pic={peak:.6f}"

    def test_overdamped_does_not_overshoot(self):
        """Sur-amorti (ζ>1) ne dépasse pas 1.0."""
        sp = SpringPhysics(stiffness=900, damping=120)  # ζ=2.0
        peak = max(sp.value(i / 1000) for i in range(1, 600))
        assert peak <= 1.0 + 1e-6, f"Spring sur-amorti ne devrait pas dépasser 1.0, pic={peak:.6f}"

    def test_three_regimes_produce_distinct_curves(self):
        """Les trois régimes produisent des valeurs distinctes à t=100ms."""
        under    = SpringPhysics(stiffness=900, damping=15)   # ζ≈0.25
        critical = SpringPhysics(stiffness=900, damping=60)   # ζ=1.0
        over_sp  = SpringPhysics(stiffness=900, damping=120)  # ζ=2.0

        v_u = under.value(0.1)
        v_c = critical.value(0.1)
        v_o = over_sp.value(0.1)

        # Chaque régime doit être différent des autres (tolérance 1%)
        assert abs(v_u - v_c) > 0.01, f"under vs critical trop proches : {v_u:.4f} vs {v_c:.4f}"
        assert abs(v_u - v_o) > 0.01, f"under vs over trop proches : {v_u:.4f} vs {v_o:.4f}"
        assert abs(v_c - v_o) > 0.01, f"critical vs over trop proches : {v_c:.4f} vs {v_o:.4f}"

    def test_underdamped_settles_faster_than_overdamped(self):
        """
        Avec les mêmes paramètres de base, le sous-amorti (ζ=0.5) atteint
        98% de la cible avant le sur-amorti (ζ=2.0).
        Prédictat connu de la mécanique : l'amortissement optimal est critique.
        """
        under = SpringPhysics(stiffness=900, damping=30)   # ζ=0.5
        over  = SpringPhysics(stiffness=900, damping=120)  # ζ=2.0

        def settle_time(sp, threshold=0.02):
            for i in range(1, 2000):
                t = i / 1000
                if abs(sp.value(t) - 1.0) < threshold:
                    return t
            return float('inf')

        t_under = settle_time(under)
        t_over  = settle_time(over)
        assert t_under < t_over, (
            f"Sous-amorti devrait settler plus vite : {t_under:.3f}s vs {t_over:.3f}s"
        )


# ─── Validation des paramètres invalides ─────────────────────────────────────

class TestInvalidParameters:
    def test_negative_stiffness_raises(self):
        """Stiffness négative est physiquement invalide."""
        with pytest.raises(ValueError, match="stiffness"):
            SpringPhysics(stiffness=-100, damping=30)

    def test_zero_stiffness_raises(self):
        """Stiffness zéro est physiquement invalide (ressort inexistant)."""
        with pytest.raises(ValueError, match="stiffness"):
            SpringPhysics(stiffness=0, damping=30)

    def test_negative_damping_raises(self):
        """Damping négatif est physiquement invalide (énergie non-conservatrice instable)."""
        with pytest.raises(ValueError, match="damping"):
            SpringPhysics(stiffness=900, damping=-5)

    def test_positive_params_do_not_raise(self):
        """Les paramètres valides ne lèvent pas d'exception."""
        sp = SpringPhysics(stiffness=0.001, damping=0.0)
        assert sp is not None


# ─── SpringLUT : cohérence avec SpringPhysics ─────────────────────────────────

class TestSpringLUT:
    def test_lut_value_at_zero(self):
        """LUT démarre à 0 comme SpringPhysics."""
        lut = SpringLUT.get(k=900, c=30, fps=60)
        assert lut.value(0.0) == pytest.approx(0.0, abs=0.01)

    def test_lut_converges(self):
        """LUT converge vers 1.0 à t=3s (limite MAX_T de la LUT)."""
        lut = SpringLUT.get(k=900, c=30, fps=60)
        assert lut.value(3.0) == pytest.approx(1.0, abs=0.01)

    def test_lut_matches_analytic(self):
        """
        LUT == SpringPhysics analytique aux points de grille natifs (±0.1%).

        La LUT utilise un indexage floor : querier à t=k*dt donne exactement la
        valeur précalculée pour ce bin (erreur = arrondi float32 seulement).
        On ne teste PAS entre les points de grille — le floor-indexing introduit
        une erreur de quantification pouvant atteindre step × velocity ≈ 0.25
        pendant la phase ascendante rapide (t ≈ 50–130ms), ce qui est attendu
        et documenté dans la spec du LUT.
        """
        k, c, fps = 900, 30, 60
        sp  = SpringPhysics(stiffness=k, damping=c)
        lut = SpringLUT.get(k=k, c=c, fps=fps)
        dt  = lut._dt  # pas natif de la LUT ≈ 16.58ms à 60fps

        # 30 premiers bins = ~500ms, couvre la phase ascendante et l'overshoot
        for i in range(31):
            t = i * dt
            assert lut.value(t) == pytest.approx(sp.value(t), abs=0.001), (
                f"Écart LUT/analytique au bin {i} (t={t*1000:.1f}ms) : "
                f"LUT={lut.value(t):.5f} analytique={sp.value(t):.5f}"
            )

    def test_lut_cache_returns_same_instance(self):
        """Même (k, c, fps) → même objet LUT (cache actif)."""
        lut1 = SpringLUT.get(k=900, c=30, fps=60)
        lut2 = SpringLUT.get(k=900, c=30, fps=60)
        assert lut1 is lut2

    def test_lut_different_params_different_instances(self):
        """Paramètres différents → instances différentes."""
        lut1 = SpringLUT.get(k=900, c=30, fps=60)
        lut2 = SpringLUT.get(k=400, c=20, fps=60)
        assert lut1 is not lut2
