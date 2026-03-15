# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Callable, List, Optional
import numpy as np

from .effects import EffectBase

@dataclass
class TimelineObject:
    t_start:   float
    t_end:     float
    render_fn: Callable
    pos_fn:    Callable     = field(default=lambda t: (0, 0))
    alpha_fn:  Callable     = field(default=lambda t: 1.0)
    z_index:   int          = 0
    effects:   List[EffectBase] = field(default_factory=list)
    tag:       str          = ""

    def is_active(self, t: float) -> bool:
        return self.t_start <= t <= self.t_end

    def get_state(self, t: float) -> Optional[dict]:
        if not self.is_active(t):
            return None
        frame = self.render_fn(t)
        if frame is None:
            return None
        for eff in self.effects:
            frame = eff.apply(frame, t, t_birth=self.t_start)
        return {
            "frame": frame,
            "pos":   self.pos_fn(t),
            "alpha": self.alpha_fn(t),
        }

class TimelineEngine:
    def __init__(self, width: int = 1080, height: int = 1920):
        self.W = width
        self.H = height
        self._objects: List[TimelineObject] = []

    def add(self, obj: TimelineObject) -> "TimelineEngine":
        self._objects.append(obj)
        return self

    def add_all(self, objs: List[TimelineObject]) -> "TimelineEngine":
        self._objects.extend(objs)
        return self

    def clear(self) -> None:
        self._objects.clear()

    def active_at(self, t: float) -> List[TimelineObject]:
        return sorted([o for o in self._objects if o.is_active(t)], key=lambda o: o.z_index)

    def render_frame(self, t: float, base_frame: np.ndarray) -> np.ndarray:
        canvas = base_frame.astype(np.float32)
        h_c, w_c = canvas.shape[:2]

        for obj in self.active_at(t):
            state = obj.get_state(t)
            if state is None:
                continue

            patch  = state["frame"]
            px, py = state["pos"]
            alpha  = float(state["alpha"])

            if alpha < 0.004 or patch is None:
                continue

            ph, pw = patch.shape[:2]

            y0s = max(0, -py);        y0d = max(0, py)
            x0s = max(0, -px);        x0d = max(0, px)
            y1s = min(ph, h_c - py);  y1d = min(h_c, py + ph)
            x1s = min(pw, w_c - px);  x1d = min(w_c, px + pw)

            if y1s <= y0s or x1s <= x0s:
                continue

            patch_sl = patch[y0s:y1s, x0s:x1s]
            bg_sl    = canvas[y0d:y1d, x0d:x1d]

            if patch_sl.ndim == 3 and patch_sl.shape[2] == 4:
                fg_a   = patch_sl[:, :, 3:4].astype(np.float32) / 255.0 * alpha
                fg_rgb = patch_sl[:, :, :3].astype(np.float32)
            else:
                fg_a   = np.full((*patch_sl.shape[:2], 1), alpha, dtype=np.float32)
                fg_rgb = patch_sl.astype(np.float32)

            canvas[y0d:y1d, x0d:x1d] = (bg_sl * (1.0 - fg_a) + fg_rgb * fg_a)

        return np.clip(canvas, 0, 255).astype(np.uint8)