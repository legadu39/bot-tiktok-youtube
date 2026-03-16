# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V29: Compositor — rendu pixel-exact, confirmé V29.
#
# PARADIGME RÉFÉRENCE (confirmé dense scan 38 frames):
#   - 1 mot = 1 WordClip
#   - Entrée: spring pop (k=900, c=30 → settle 200ms = 6 frames)
#   - Exit : HARD CUT (t >= t_end strict → invisible, 0 frame fondu)
#   - Y    : TEXT_ANCHOR_Y_RATIO = 0.4951H FIXE (ne bouge JAMAIS)
#   - Wiggle: 5px sur ACCENT/BADGE, décroît sur 200ms
#
# V29 vs V25: Aucun changement de logique — les mesures confirment tout.
# Seule correction: TEXT_ANCHOR_Y_RATIO 0.4970 → 0.4951 (héritée de config.py)

from __future__ import annotations
import numpy as np
from PIL import Image
from typing import List, Tuple

from .physics import SpringPhysics, wiggle_offset
from .easing  import EasingLibrary
from .config  import TEXT_ANCHOR_Y_RATIO, SPRING_SLIDE_PX


class WordClip:
    """
    ARCHITECTURE_MASTER_V29: Objet texte individuel.

    Champs:
        arr / arr_inv : rendu RGBA normal / inversé (pré-calculé)
        target_x/y   : position destination (spring settle là)
        t_start       : apparition (entrée spring)
        t_end         : disparition EXACTE (hard cut — t >= t_end)
        is_keyword    : True → wiggle 5px actif 200ms
        spring        : instance SpringPhysics(900, 30)
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
    ARCHITECTURE_MASTER_V29: Zoom centré continu.
    zoom 1.00→1.03 sur toute la durée (ease_in_out_sine en amont).
    BICUBIC: meilleur speed/quality tradeoff pour delta 3%.
    """
    if abs(zoom_scale - 1.0) < 0.001:
        return frame
    h, w  = frame.shape[:2]
    nw    = max(w, int(w * zoom_scale))
    nh    = max(h, int(h * zoom_scale))
    img   = Image.fromarray(frame).resize((nw, nh), Image.BICUBIC)
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
    ARCHITECTURE_MASTER_V29: Compositor principal frame-par-frame.

    ALGORITHME par WordClip actif (t_start ≤ t < t_end):
        1. t_elapsed = t - t_start
        2. spring.value(elapsed) → raw scale (peut > 1.0 overshoot)
        3. spring.clamped(elapsed) → alpha [0,1]
        4. alpha clampé AVANT blend (raw > 1.0 = overshoot intentionnel)
        5. wiggle_offset si is_keyword (5px, 200ms)
        6. Resize PIL si |scale-1| > 0.003
        7. Alpha-blend Porter-Duff Over

    HARD CUT: t >= t_end → clip invisible instantanément.
    """
    frame = np.copy(base_frame)

    for c in clips:
        if t < c.t_start or t >= c.t_end:
            continue

        elapsed = t - c.t_start
        raw     = c.spring.value(elapsed)
        alpha   = c.spring.clamped(elapsed)
        scale   = max(0.0, raw)
        y_off   = int(SPRING_SLIDE_PX * max(0.0, 1.0 - alpha))

        if alpha < 0.004:
            continue

        shake_dx, shake_dy = 0, 0
        if c.is_keyword:
            shake_dx, shake_dy = wiggle_offset(elapsed, amp=5.0, decay=5.0)

        x_pos = c.target_x + shake_dx
        y_pos = c.target_y + shake_dy + y_off

        arr = c.arr_inv if inverted else c.arr
        h, w = arr.shape[:2]

        if abs(scale - 1.0) > 0.003:
            nh  = max(1, int(h * scale))
            nw  = max(1, int(w * scale))
            img = Image.fromarray(arr).resize((nw, nh), Image.BILINEAR)
            arr = np.array(img)
            h, w = nh, nw
            y_pos += (c.h - h) // 2
            x_pos += (c.w - w) // 2

        y0s = max(0, -y_pos);        y0d = max(0, y_pos)
        x0s = max(0, -x_pos);        x0d = max(0, x_pos)
        y1s = min(h, vid_h - y_pos); y1d = min(vid_h, y_pos + h)
        x1s = min(w, vid_w - x_pos); x1d = min(vid_w, x_pos + w)

        if y1s <= y0s or x1s <= x0s:
            continue

        patch  = arr[y0s:y1s, x0s:x1s]
        bg_sl  = frame[y0d:y1d, x0d:x1d].astype(np.float32)

        if patch.shape[2] == 4:
            fg_a   = patch[:, :, 3:4].astype(np.float32) / 255.0 * alpha
            fg_rgb = patch[:, :, :3].astype(np.float32)
        else:
            fg_a   = np.full(patch.shape[:2] + (1,), alpha, dtype=np.float32)
            fg_rgb = patch.astype(np.float32)

        blended = bg_sl * (1.0 - fg_a) + fg_rgb * fg_a
        frame[y0d:y1d, x0d:x1d] = blended.clip(0, 255).astype(np.uint8)

    return frame


def compose_frame_layered(
    t:          float,
    layers:     List[List[WordClip]],
    vid_w:      int,
    vid_h:      int,
    base_frame: np.ndarray,
    inverted:   bool = False,
) -> np.ndarray:
    """Multi-layer variant (couche 0=fond, -1=devant)."""
    frame = np.copy(base_frame)
    for layer in layers:
        frame = compose_frame(t, layer, vid_w, vid_h, frame, inverted)
    return frame


def precompute_spring_positions(clips: List[WordClip], fps: int = 30) -> dict:
    """Pré-calcule positions spring par frame (debug/export HR)."""
    positions = {}
    for i, c in enumerate(clips):
        clip_positions = {}
        start_frame    = max(0, int(c.t_start * fps))
        end_frame      = int(c.t_end * fps) + 1
        for f_idx in range(start_frame, end_frame):
            t       = f_idx / fps
            elapsed = t - c.t_start
            if elapsed < 0:
                continue
            raw   = c.spring.value(elapsed)
            alpha = c.spring.clamped(elapsed)
            scale = max(0.0, raw)
            y_off = int(SPRING_SLIDE_PX * max(0.0, 1.0 - alpha))
            clip_positions[f_idx] = (c.target_x, c.target_y + y_off, scale, alpha)
        positions[i] = clip_positions
    return positions