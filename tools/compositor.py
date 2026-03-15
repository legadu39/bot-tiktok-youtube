# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image
from typing import List

from .physics import SpringPhysics, ease_in_expo, wiggle_offset
from .vfx import draw_sparkles

class WordClip:
    __slots__ = (
        "arr", "arr_inv", "w", "h", "target_x", "target_y",
        "t_start", "t_entry_end", "t_exit_start", "t_full_end",
        "is_keyword", "slide_px_out", "_spring",
    )

    def __init__(self, arr: np.ndarray, arr_inv: np.ndarray, target_x: int, target_y: int, t_start: float, t_entry_end: float, t_exit_start: float, t_full_end: float, is_keyword: bool = False, slide_px_out: int = 550):
        self.arr          = arr
        self.arr_inv      = arr_inv
        self.h, self.w    = arr.shape[:2]
        self.target_x     = target_x
        self.target_y     = target_y
        self.t_start      = t_start
        self.t_entry_end  = t_entry_end
        self.t_exit_start = t_exit_start
        self.t_full_end   = t_full_end
        self.is_keyword   = is_keyword
        self.slide_px_out = slide_px_out
        self._spring      = SpringPhysics(stiffness=625, damping=25)

def apply_continuous_zoom(frame: np.ndarray, zoom_scale: float) -> np.ndarray:
    if abs(zoom_scale - 1.0) < 0.001:
        return frame
    h, w  = frame.shape[:2]
    nw    = max(w, int(w * zoom_scale))
    nh    = max(h, int(h * zoom_scale))
    img   = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
    arr   = np.array(img)
    y0    = (nh - h) // 2
    x0    = (nw - w) // 2
    return arr[y0:y0+h, x0:x0+w]

def compose_frame(t: float, clips: List[WordClip], vid_w: int, vid_h: int, base_frame: np.ndarray, inverted: bool = False, particles: List = None) -> np.ndarray:
    frame = np.copy(base_frame)

    for c in clips:
        if t < c.t_start or t > c.t_full_end:
            continue

        elapsed = t - c.t_start
        SLIDE_UP_PX = 15

        spring_raw   = c._spring.value(elapsed)
        alpha_in     = c._spring.clamped(elapsed)
        scale        = max(0.0, spring_raw)
        y_offset     = int(SLIDE_UP_PX * max(0.0, 1.0 - alpha_in))

        if alpha_in < 0.004:
            continue

        shake_dx, shake_dy = (0, 0)
        if c.is_keyword:
            shake_dx, shake_dy = wiggle_offset(elapsed, amp=5.0, decay=5.0)

        y_pos = c.target_y + shake_dy + y_offset
        x_pos = c.target_x + shake_dx
        alpha = min(1.0, alpha_in)

        arr = c.arr_inv if inverted else c.arr
        h, w = arr.shape[:2]

        if t >= c.t_exit_start:
            exit_dur  = max(c.t_full_end - c.t_exit_start, 1e-6)
            exit_p    = min((t - c.t_exit_start) / exit_dur, 1.0)
            exit_ease = ease_in_expo(exit_p)
            y_pos    -= int(c.slide_px_out * exit_ease)
            alpha     = alpha * max(0.0, 1.0 - exit_ease ** 2)

        if alpha < 0.004:
            continue

        if abs(scale - 1.0) > 0.003:
            nh  = max(1, int(h * scale))
            nw  = max(1, int(w * scale))
            img = Image.fromarray(arr).resize((nw, nh), Image.LANCZOS)
            arr = np.array(img)
            h, w = nh, nw
            y_pos += (c.h - h) // 2
            x_pos += (c.w - w) // 2

        y0s = max(0, -y_pos);       y0d = max(0, y_pos)
        x0s = max(0, -x_pos);       x0d = max(0, x_pos)
        y1s = min(h, vid_h - y_pos); y1d = min(vid_h, y_pos + h)
        x1s = min(w, vid_w - x_pos); x1d = min(vid_w, x_pos + w)

        if y1s <= y0s or x1s <= x0s:
            continue

        patch  = arr[y0s:y1s, x0s:x1s]
        bg_sl  = frame[y0d:y1d, x0d:x1d].astype(np.float32)

        if patch.shape[2] == 4:
            fg_a   = patch[:,:,3:4].astype(np.float32) / 255.0 * alpha
            fg_rgb = patch[:,:,:3].astype(np.float32)
        else:
            fg_a   = np.full(patch.shape[:2] + (1,), alpha, dtype=np.float32)
            fg_rgb = patch.astype(np.float32)

        blended = bg_sl * (1.0 - fg_a) + fg_rgb * fg_a
        frame[y0d:y1d, x0d:x1d] = blended.clip(0, 255).astype(np.uint8)

    if inverted and particles:
        frame = draw_sparkles(frame, particles, t, inverted=True)

    return frame