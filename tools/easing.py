# -*- coding: utf-8 -*-
import math

class EasingLibrary:
    """Arsenal complet de courbes d'accélération."""

    @staticmethod
    def linear(p: float) -> float:
        return max(0.0, min(1.0, p))

    @staticmethod
    def ease_out_cubic(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 1.0 - (1.0 - p) ** 3

    @staticmethod
    def ease_in_cubic(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return p * p * p

    @staticmethod
    def ease_in_out_sine(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return -(math.cos(math.pi * p) - 1.0) / 2.0

    @staticmethod
    def ease_in_expo(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 0.0 if p == 0.0 else pow(2.0, 10.0 * (p - 1.0))

    @staticmethod
    def ease_out_expo(p: float) -> float:
        p = max(0.0, min(1.0, p))
        return 1.0 if p == 1.0 else 1.0 - pow(2.0, -10.0 * p)

    @staticmethod
    def ease_out_back(p: float, overshoot: float = 1.70158) -> float:
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