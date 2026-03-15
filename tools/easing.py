# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Arsenal complet de courbes d'accélération.
# Chaque méthode : p ∈ [0,1] → valeur ∈ [0,1] (sauf ease_out_back qui peut dépasser).
# Toutes les fonctions sont statiques — zéro instanciation nécessaire.

import math


class EasingLibrary:
    """
    ARCHITECTURE_MASTER_V22 : Bibliothèque statique de courbes.

    Courbes utilisées dans la référence (reverse-engineered) :
    • Entrée texte  : SpringPhysics.snap() — pas une courbe Bézier
    • Zoom global   : ease_in_out_sine (continu, très subtil)
    • Exit slide-up : ease_in_expo (accélération rapide → swipe up brutal)
    • Underline draw: ease_out_expo (précision millimétrique)
    • Transitions   : ease_out_back (snap back sur slide)
    """

    @staticmethod
    def linear(p: float) -> float:
        return max(0.0, min(1.0, p))

    @staticmethod
    def ease_out_cubic(p: float) -> float:
        """Décélération douce — standard industriel."""
        p = max(0.0, min(1.0, p))
        return 1.0 - (1.0 - p) ** 3

    @staticmethod
    def ease_in_cubic(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return p * p * p

    @staticmethod
    def ease_in_out_sine(p: float) -> float:
        """
        ARCHITECTURE_MASTER_V22 : Zoom global de la référence.
        Sinusoïdale douce — imperceptible frame à frame, visible sur la durée.
        """
        p = max(0.0, min(1.0, p))
        return -(math.cos(math.pi * p) - 1.0) / 2.0

    @staticmethod
    def ease_in_expo(p: float) -> float:
        """
        ARCHITECTURE_MASTER_V22 : Exit slide-up de la référence.
        Départ quasi-nul puis explosion → effet swipe-up impactant.
        """
        p = max(0.0, min(1.0, p))
        return 0.0 if p == 0.0 else pow(2.0, 10.0 * (p - 1.0))

    @staticmethod
    def ease_out_expo(p: float) -> float:
        """
        ARCHITECTURE_MASTER_V22 : Underline draw de la référence.
        Décélération exponentielle — précision millimétrique à la fin.
        """
        p = max(0.0, min(1.0, p))
        return 1.0 if p == 1.0 else 1.0 - pow(2.0, -10.0 * p)

    @staticmethod
    def ease_out_back(p: float, overshoot: float = 1.70158) -> float:
        """
        ARCHITECTURE_MASTER_V22 : Slide transition spring-back.
        Dépasse la cible puis revient — 'snap & bounce'.
        overshoot=1.70 (défaut) → discret ; overshoot=2.5 → prononcé.
        """
        p = max(0.0, min(1.0, p))
        c1 = overshoot
        c3 = c1 + 1.0
        return 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2

    @staticmethod
    def ease_in_out_cubic(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 4.0 * p * p * p if p < 0.5 else 1.0 - (-2.0 * p + 2.0) ** 3 / 2.0

    @staticmethod
    def ease_out_quart(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 1.0 - (1.0 - p) ** 4

    @staticmethod
    def ease_out_sine(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return math.sin(p * math.pi / 2.0)