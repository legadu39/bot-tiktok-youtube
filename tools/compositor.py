# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Compositeur de frames.
# Gère le rendu pixel-perfect des WordClip sur le canvas.
#
# PARADIGME RÉFÉRENCE :
#   - 1 mot = 1 WordClip
#   - Entrée : spring pop (80ms)
#   - Exit   : HARD CUT (0 frame de fondu)
#   - Position : centrée H+V sur TEXT_ANCHOR_Y_RATIO = 0.499

from __future__ import annotations
import numpy as np
from PIL import Image
from typing import List, Tuple

from .physics import SpringPhysics, wiggle_offset
from .easing  import EasingLibrary
from .config  import TEXT_ANCHOR_Y_RATIO, SPRING_SLIDE_PX


class WordClip:
    """
    ARCHITECTURE_MASTER_V22 : Objet texte individuel pour le compositor.

    Champs clés :
        arr / arr_inv   : rendu RGBA normal / inversé
        target_x/y      : position de destination (spring se stabilise là)
        t_start         : apparition (entrée spring)
        t_end           : disparition EXACTE (hard cut — pas de fade)
        is_keyword      : True → wiggle actif
        spring          : instance SpringPhysics configurée
    """

    __slots__ = (
        "arr", "arr_inv", "w", "h",
        "target_x", "target_y",
        "t_start", "t_end",
        "is_keyword", "spring",
    )

    def __init__(
        self,
        arr:        np.ndarray,
        arr_inv:    np.ndarray,
        target_x:   int,
        target_y:   int,
        t_start:    float,
        t_end:      float,
        is_keyword: bool          = False,
        spring:     SpringPhysics = None,
    ):
        self.arr        = arr
        self.arr_inv    = arr_inv
        self.h, self.w  = arr.shape[:2]
        self.target_x   = target_x
        self.target_y   = target_y
        self.t_start    = t_start
        self.t_end      = t_end
        self.is_keyword = is_keyword
        self.spring     = spring or SpringPhysics.snap()


def apply_continuous_zoom(frame: np.ndarray, zoom_scale: float) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22 : Zoom centré sur le frame.
    scale=1.03 → imperceptible frame-à-frame, visible sur la durée.
    """
    if abs(zoom_scale - 1.0) < 0.001:
        return frame
    h, w  = frame.shape[:2]
    nw    = max(w, int(w * zoom_scale))
    nh    = max(h, int(h * zoom_scale))
    img   = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
    arr   = np.array(img)
    y0    = (nh - h) // 2
    x0    = (nw - w) // 2
    return arr[y0:y0 + h, x0:x0 + w]


def compose_frame(
    t:          float,
    clips:      List[WordClip],
    vid_w:      int,
    vid_h:      int,
    base_frame: np.ndarray,
    inverted:   bool = False,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22 : Compositor principal.

    Algorithme par WordClip actif (t_start ≤ t < t_end) :
        1. Calculer t_elapsed = t - t_start
        2. spring.value(t_elapsed) → scale + alpha + y_offset
        3. Optionnel : wiggle_offset si is_keyword
        4. Alpha-blend (Porter-Duff Over) sur base_frame

    NOTE HARD CUT : le test est `t < c.t_end` (strict <).
    Le mot disparaît à l'instant exact, sans fondu résiduel.
    """
    frame = np.copy(base_frame)

    for c in clips:
        # HARD CUT : strict < (pas ≤)
        if t < c.t_start or t >= c.t_end:
            continue

        elapsed = t - c.t_start

        # ── Spring physics ────────────────────────────────────────────────
        raw   = c.spring.value(elapsed)
        alpha = c.spring.clamped(elapsed)
        scale = max(0.0, raw)
        y_off = int(SPRING_SLIDE_PX * max(0.0, 1.0 - alpha))

        if alpha < 0.004:
            continue

        # ── Wiggle sur mots-clés ─────────────────────────────────────────
        shake_dx, shake_dy = 0, 0
        if c.is_keyword:
            shake_dx, shake_dy = wiggle_offset(elapsed, amp=5.0, decay=5.0)

        x_pos = c.target_x + shake_dx
        y_pos = c.target_y + shake_dy + y_off

        arr = c.arr_inv if inverted else c.arr
        h, w = arr.shape[:2]

        # ── Mise à l'échelle spring ───────────────────────────────────────
        if abs(scale - 1.0) > 0.003:
            nh  = max(1, int(h * scale))
            nw  = max(1, int(w * scale))
            img = Image.fromarray(arr).resize((nw, nh), Image.LANCZOS)
            arr = np.array(img)
            h, w = nh, nw
            y_pos += (c.h - h) // 2
            x_pos += (c.w - w) // 2

        # ── Clipping ────────────────────────────────────────────────────
        y0s = max(0, -y_pos);        y0d = max(0, y_pos)
        x0s = max(0, -x_pos);        x0d = max(0, x_pos)
        y1s = min(h, vid_h - y_pos); y1d = min(vid_h, y_pos + h)
        x1s = min(w, vid_w - x_pos); x1d = min(vid_w, x_pos + w)

        if y1s <= y0s or x1s <= x0s:
            continue

        patch  = arr[y0s:y1s, x0s:x1s]
        bg_sl  = frame[y0d:y1d, x0d:x1d].astype(np.float32)

        # ── Alpha-blending ───────────────────────────────────────────────
        if patch.shape[2] == 4:
            fg_a   = patch[:, :, 3:4].astype(np.float32) / 255.0 * alpha
            fg_rgb = patch[:, :, :3].astype(np.float32)
        else:
            fg_a   = np.full(patch.shape[:2] + (1,), alpha, dtype=np.float32)
            fg_rgb = patch.astype(np.float32)

        blended = bg_sl * (1.0 - fg_a) + fg_rgb * fg_a
        frame[y0d:y1d, x0d:x1d] = blended.clip(0, 255).astype(np.uint8)

    return frame