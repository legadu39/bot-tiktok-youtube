# -*- coding: utf-8 -*-
import math
from typing import Tuple
import numpy as np
from PIL import Image

from .easing import EasingLibrary
from .physics import SpringPhysics

class EffectBase:
    def apply(self, frame: np.ndarray, t: float, **kwargs) -> np.ndarray:
        raise NotImplementedError

class EffectContinuousZoom(EffectBase):
    def __init__(self, duration: float, scale_start: float = 1.00, scale_end: float = 1.04, easing: str = "sine"):
        self.duration    = max(duration, 1e-6)
        self.scale_start = scale_start
        self.scale_end   = scale_end
        _map = {
            "sine":   EasingLibrary.ease_in_out_sine,
            "linear": EasingLibrary.linear,
            "cubic":  EasingLibrary.ease_in_out_cubic,
        }
        self._ease = _map.get(easing, EasingLibrary.ease_in_out_sine)

    def scale_at(self, t: float) -> float:
        p     = t / self.duration
        eased = self._ease(p)
        return self.scale_start + (self.scale_end - self.scale_start) * eased

    def apply(self, frame: np.ndarray, t: float, **_) -> np.ndarray:
        scale = self.scale_at(t)
        if abs(scale - 1.0) < 0.001:
            return frame
        h, w  = frame.shape[:2]
        nw    = max(w, int(w * scale))
        nh    = max(h, int(h * scale))
        img   = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
        arr   = np.array(img)
        y0    = (nh - h) // 2
        x0    = (nw - w) // 2
        return arr[y0:y0 + h, x0:x0 + w]

class EffectSpringOvershoot(EffectBase):
    def __init__(self, spring: SpringPhysics = None, slide_px: int = 15):
        self.spring   = spring or SpringPhysics.reference_pop()
        self.slide_px = slide_px

    def state_at(self, t_elapsed: float) -> dict:
        raw   = self.spring.value(t_elapsed)
        alpha = self.spring.clamped(t_elapsed)
        scale = max(0.0, raw)
        y_off = int(self.slide_px * max(0.0, 1.0 - alpha))
        return {"scale": scale, "alpha": alpha, "y_offset": y_off}

    def apply(self, frame: np.ndarray, t: float, **_) -> np.ndarray:
        state = self.state_at(t)
        s = state["scale"]
        if abs(s - 1.0) < 0.003:
            return frame
        h, w = frame.shape[:2]
        nh   = max(1, int(h * s))
        nw   = max(1, int(w * s))
        img  = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
        return np.array(img)

class EffectWiggle(EffectBase):
    def __init__(self, frequency: float = 8.0, amplitude: float = 5.0, decay: float = 5.0, active_ms: float = 200.0):
        self.freq      = frequency
        self.amp       = amplitude
        self.decay     = decay
        self.active_s  = active_ms / 1000.0

    def offset(self, t_elapsed: float) -> Tuple[int, int]:
        if t_elapsed >= self.active_s or t_elapsed < 0.0:
            return 0, 0
        envelope = math.exp(-self.decay * t_elapsed) * (1.0 - t_elapsed / self.active_s)
        dx = math.sin(t_elapsed * self.freq * math.pi) * self.amp * envelope
        dy = math.cos(t_elapsed * self.freq * math.e)  * self.amp * envelope
        return int(round(dx)), int(round(dy))

    def apply(self, frame: np.ndarray, t: float, t_birth: float = 0.0, **_) -> np.ndarray:
        dx, dy = self.offset(t - t_birth)
        if dx == 0 and dy == 0:
            return frame
        h, w = frame.shape[:2]
        result = np.zeros_like(frame)
        src = np.roll(np.roll(frame, dy, axis=0), dx, axis=1)
        result[:h, :w] = src[:h, :w]
        return result