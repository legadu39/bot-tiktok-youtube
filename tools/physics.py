# -*- coding: utf-8 -*-
import math
from typing import Tuple

def ease_out_cubic(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3

def ease_in_expo(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 0.0 if p == 0.0 else pow(2.0, 10.0 * (p - 1.0))

def ease_out_expo(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1.0 if p == 1.0 else 1.0 - pow(2.0, -10.0 * p)

def ease_in_out_sine(p: float) -> float:
    return -(math.cos(math.pi * max(0.0, min(1.0, p))) - 1.0) / 2.0

class SpringPhysics:
    def __init__(self, stiffness: float = 625.0, damping: float = 25.0):
        self.omega0    = math.sqrt(max(stiffness, 1e-6))
        self.zeta      = damping / (2.0 * self.omega0)
        zeta_sq        = max(1.0 - self.zeta**2, 1e-12)
        self.omega_d   = self.omega0 * math.sqrt(zeta_sq)
        self.sin_coeff = self.zeta / math.sqrt(zeta_sq)

    def value(self, t: float) -> float:
        t   = max(0.0, t)
        env = math.exp(-self.zeta * self.omega0 * t)
        return 1.0 - env * (
            math.cos(self.omega_d * t)
            + self.sin_coeff * math.sin(self.omega_d * t)
        )

    def clamped(self, t: float) -> float:
        return max(0.0, min(1.0, self.value(t)))

    def state(self, t_elapsed: float, slide_px: int = 15) -> dict:
        raw   = self.value(t_elapsed)
        alpha = self.clamped(t_elapsed)
        scale = max(0.0, raw)
        y_off = int(slide_px * max(0.0, 1.0 - alpha))
        return {"scale": scale, "alpha": alpha, "y_offset": y_off}

def wiggle_offset(t_elapsed: float, amp: float = 5.0, decay: float = 5.0) -> Tuple[int, int]:
    if t_elapsed >= 0.2 or t_elapsed < 0.0:
        return 0, 0
    envelope = math.exp(-decay * t_elapsed) * (1.0 - t_elapsed / 0.2)
    dx = math.sin(t_elapsed * 8.0 * math.pi) * amp * envelope
    dy = math.cos(t_elapsed * 8.0 * math.e)  * amp * envelope
    return int(round(dx)), int(round(dy))