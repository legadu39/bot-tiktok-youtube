"""
Tests pour tools/easing.py — EasingLibrary.

Pourquoi c'est critique : les fonctions d'easing contrôlent toutes les animations
hors spring (zoom global, exit slide-up, underline draw, transitions). Une violation
des bornes (f(0) != 0 ou f(1) != 1) décale silencieusement la position de départ ou
d'arrivée de chaque objet animé dans la vidéo finale.

Note sur ease_out_back : cette fonction dépasse intentionnellement 1.0 en milieu
de courbe (effet "snap & bounce"). Elle est exclue des tests de plage [0,1] mais
doit respecter f(0)=0 et f(1)=1.

Tests couverts :
- Bornes exactes : f(0) = 0.0, f(1) = 1.0 pour toutes les fonctions
- Plage [0,1] pour les inputs [0,1] (sauf ease_out_back)
- Monotonicité : ease_in et ease_out sont strictement non-décroissantes
- ease_out_back : bornes respectées, overshoot présent entre 0 et 1
"""

import math
import pytest
from tools.easing import EasingLibrary

# Fonctions standard : sortie garantie dans [0, 1]
STANDARD_FNS = [
    ("linear",            EasingLibrary.linear),
    ("ease_out_cubic",    EasingLibrary.ease_out_cubic),
    ("ease_in_cubic",     EasingLibrary.ease_in_cubic),
    ("ease_in_out_sine",  EasingLibrary.ease_in_out_sine),
    ("ease_in_expo",      EasingLibrary.ease_in_expo),
    ("ease_out_expo",     EasingLibrary.ease_out_expo),
    ("ease_in_out_cubic", EasingLibrary.ease_in_out_cubic),
    ("ease_out_quart",    EasingLibrary.ease_out_quart),
    ("ease_out_sine",     EasingLibrary.ease_out_sine),
]

# Fonctions monotones : toutes les ease_in et ease_out standard
MONOTONIC_FNS = [
    ("linear",         EasingLibrary.linear),
    ("ease_out_cubic", EasingLibrary.ease_out_cubic),
    ("ease_in_cubic",  EasingLibrary.ease_in_cubic),
    ("ease_in_expo",   EasingLibrary.ease_in_expo),
    ("ease_out_expo",  EasingLibrary.ease_out_expo),
    ("ease_out_quart", EasingLibrary.ease_out_quart),
    ("ease_out_sine",  EasingLibrary.ease_out_sine),
]


# ─── Bornes f(0) = 0 et f(1) = 1 ────────────────────────────────────────────

@pytest.mark.parametrize("name,fn", STANDARD_FNS)
def test_boundary_zero(name, fn):
    """Toutes les fonctions standard : f(0.0) == 0.0 exactement."""
    assert fn(0.0) == pytest.approx(0.0, abs=1e-9), f"{name}(0) = {fn(0.0)}"


@pytest.mark.parametrize("name,fn", STANDARD_FNS)
def test_boundary_one(name, fn):
    """Toutes les fonctions standard : f(1.0) == 1.0 exactement."""
    assert fn(1.0) == pytest.approx(1.0, abs=1e-9), f"{name}(1) = {fn(1.0)}"


# ─── Plage de sortie [0, 1] ──────────────────────────────────────────────────

@pytest.mark.parametrize("name,fn", STANDARD_FNS)
def test_output_in_range(name, fn):
    """Pour p ∈ [0, 1] (100 échantillons), la sortie reste dans [0, 1]."""
    samples = [i / 100 for i in range(101)]
    for p in samples:
        v = fn(p)
        assert 0.0 <= v <= 1.0, (
            f"{name}({p:.2f}) = {v:.6f} hors de [0, 1]"
        )


# ─── ease_out_back : cas spécial ─────────────────────────────────────────────

def test_ease_out_back_boundary_zero():
    """ease_out_back : f(0) == 0."""
    assert EasingLibrary.ease_out_back(0.0) == pytest.approx(0.0, abs=1e-9)


def test_ease_out_back_boundary_one():
    """ease_out_back : f(1) == 1."""
    assert EasingLibrary.ease_out_back(1.0) == pytest.approx(1.0, abs=1e-9)


def test_ease_out_back_overshoots():
    """ease_out_back dépasse intentionnellement 1.0 en milieu de courbe."""
    samples = [i / 1000 for i in range(1, 1000)]
    peak = max(EasingLibrary.ease_out_back(p) for p in samples)
    assert peak > 1.0, f"ease_out_back devrait dépasser 1.0, pic = {peak:.4f}"


# ─── Monotonicité ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,fn", MONOTONIC_FNS)
def test_monotonically_increasing(name, fn):
    """
    Toutes les fonctions ease_in / ease_out sont strictement non-décroissantes.
    Tolérance 1e-10 pour les erreurs flottantes au niveau du dernier bit.
    """
    samples = [i / 1000 for i in range(1001)]
    values  = [fn(p) for p in samples]
    for i in range(1, len(values)):
        assert values[i] >= values[i - 1] - 1e-10, (
            f"{name} non-monotone à p={samples[i]:.3f} : "
            f"{values[i-1]:.8f} → {values[i]:.8f}"
        )


# ─── Clamp des entrées hors bornes ───────────────────────────────────────────

@pytest.mark.parametrize("name,fn", STANDARD_FNS)
def test_clamp_below_zero(name, fn):
    """f(p < 0) est clampé — ne peut pas retourner < 0."""
    assert fn(-0.5) >= 0.0, f"{name}(-0.5) retourne une valeur négative"


@pytest.mark.parametrize("name,fn", STANDARD_FNS)
def test_clamp_above_one(name, fn):
    """f(p > 1) est clampé — ne peut pas retourner > 1."""
    assert fn(1.5) <= 1.0, f"{name}(1.5) retourne une valeur > 1"


# ─── Valeurs spot-check connues ───────────────────────────────────────────────

def test_ease_out_cubic_midpoint():
    """ease_out_cubic(0.5) = 1 - (0.5)^3 = 0.875."""
    assert EasingLibrary.ease_out_cubic(0.5) == pytest.approx(0.875, abs=1e-9)


def test_ease_in_cubic_midpoint():
    """ease_in_cubic(0.5) = 0.5^3 = 0.125."""
    assert EasingLibrary.ease_in_cubic(0.5) == pytest.approx(0.125, abs=1e-9)


def test_ease_in_out_sine_midpoint():
    """ease_in_out_sine(0.5) = 0.5 (symétrie sinusoïdale)."""
    assert EasingLibrary.ease_in_out_sine(0.5) == pytest.approx(0.5, abs=1e-9)


def test_linear_is_identity():
    """linear est une identité clampée sur [0, 1]."""
    for p in [0.0, 0.25, 0.5, 0.75, 1.0]:
        assert EasingLibrary.linear(p) == pytest.approx(p, abs=1e-9)
