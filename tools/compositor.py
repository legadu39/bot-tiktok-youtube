# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V25: Compositeur de frames — rendu pixel-exact.
#
# PARADIGME RÉFÉRENCE (confirmé V25 par analyse dense) :
#   - 1 mot = 1 WordClip
#   - Entrée  : spring pop (k=900, c=30 → settle 200ms = 6 frames)
#   - Exit    : HARD CUT (t >= t_end strict → invisible immédiatement)
#   - Position: centrée H+V sur TEXT_ANCHOR_Y_RATIO = 0.4970
#   - Wiggle  : 5px sur ACCENT/BADGE, décroît sur 200ms
#
# CORRECTION V25 vs V24 :
#   apply_continuous_zoom() : interpolation LANCZOS → BICUBIC pour vitesse
#   compose_frame() : clamp alpha avant blend (évite artefacts >1.0 du spring)

from __future__ import annotations
import numpy as np
from PIL import Image
from typing import List, Tuple

from .physics import SpringPhysics, wiggle_offset
from .easing  import EasingLibrary
from .config  import TEXT_ANCHOR_Y_RATIO, SPRING_SLIDE_PX


class WordClip:
    """
    ARCHITECTURE_MASTER_V25 : Objet texte individuel pour le compositor.

    Champs clés :
        arr / arr_inv   : rendu RGBA normal / inversé (pré-calculé)
        target_x/y      : position de destination (spring se stabilise là)
        t_start         : apparition (entrée spring)
        t_end           : disparition EXACTE (hard cut — t >= t_end)
        is_keyword      : True → wiggle 5px actif
        spring          : instance SpringPhysics (k=900, c=30 par défaut)
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
    ARCHITECTURE_MASTER_V25 : Zoom centré continu.
    scale=1.03 → imperceptible frame-à-frame, visible sur la durée totale.

    Utilise BICUBIC pour le speed-quality tradeoff optimal.
    LANCZOS est plus précis mais 2× plus lent sans bénéfice visible à ce niveau
    de zoom (1.00→1.03, delta de 3%).
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
    ARCHITECTURE_MASTER_V25 : Compositor principal — pipeline frame-par-frame.

    ALGORITHME par WordClip actif (t_start ≤ t < t_end) :
        1. t_elapsed = t - t_start
        2. spring.value(t_elapsed) → raw scale (peut dépasser 1.0)
        3. spring.clamped(t_elapsed) → alpha [0,1]
        4. CORRECTION V25 : alpha clampé AVANT blend (raw > 1.0 possible)
        5. Optionnel : wiggle_offset si is_keyword (5px, 200ms)
        6. Redimensionnement PIL si |scale-1| > 0.003
        7. Alpha-blend Porter-Duff Over sur base_frame

    HARD CUT : test `t >= t_end` strict.
    Le mot disparaît EXACTEMENT à l'instant de l'entrée du mot suivant.
    Aucun frame de fondu ne l'accompagne — c'est la signature rythmique
    de la référence.

    NOTE overshoot : raw > 1.0 (jusqu'à 1.15 au pic) → scale > 1.
    Le mot est donc légèrement plus grand pendant ~3 frames. C'est intentionnel.
    La clampe s'applique UNIQUEMENT sur alpha (opacité), pas sur scale.
    """
    frame = np.copy(base_frame)

    for c in clips:
        # HARD CUT strict : t >= t_end → invisible
        if t < c.t_start or t >= c.t_end:
            continue

        elapsed = t - c.t_start

        # ── Spring physics ────────────────────────────────────────────────
        raw   = c.spring.value(elapsed)
        alpha = c.spring.clamped(elapsed)   # [0,1] — pour opacité uniquement
        scale = max(0.0, raw)               # peut être > 1.0 (overshoot)
        y_off = int(SPRING_SLIDE_PX * max(0.0, 1.0 - alpha))

        # ARCHITECTURE_MASTER_V25: Skip si alpha négligeable (<0.4%)
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
        # ARCHITECTURE_MASTER_V25: On applique le scale Y ET X
        # pour un zoom isotropique correct (pas juste la hauteur)
        if abs(scale - 1.0) > 0.003:
            nh  = max(1, int(h * scale))
            nw  = max(1, int(w * scale))
            img = Image.fromarray(arr).resize((nw, nh), Image.BILINEAR)
            arr = np.array(img)
            h, w = nh, nw
            # Recentrer après scale (le target_x/y était calculé pour scale=1.0)
            y_pos += (c.h - h) // 2
            x_pos += (c.w - w) // 2

        # ── Clipping ─────────────────────────────────────────────────────
        y0s = max(0, -y_pos);        y0d = max(0, y_pos)
        x0s = max(0, -x_pos);        x0d = max(0, x_pos)
        y1s = min(h, vid_h - y_pos); y1d = min(vid_h, y_pos + h)
        x1s = min(w, vid_w - x_pos); x1d = min(vid_w, x_pos + w)

        if y1s <= y0s or x1s <= x0s:
            continue

        patch  = arr[y0s:y1s, x0s:x1s]
        bg_sl  = frame[y0d:y1d, x0d:x1d].astype(np.float32)

        # ── Alpha-blending Porter-Duff Over ───────────────────────────────
        # ARCHITECTURE_MASTER_V25: alpha de l'image × alpha global du spring
        # L'image peut être RGBA (texte rendu avec canal alpha) ou RGB
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
    """
    ARCHITECTURE_MASTER_V25: Variant multi-layer.
    Compose N listes de WordClips dans l'ordre (couche 0 = fond, -1 = devant).
    Utilisé quand on veut placer certains mots derrière d'autres.
    """
    frame = np.copy(base_frame)
    for layer in layers:
        frame = compose_frame(t, layer, vid_w, vid_h, frame, inverted)
    return frame


def precompute_spring_positions(
    clips:  List[WordClip],
    fps:    int = 30,
) -> dict:
    """
    ARCHITECTURE_MASTER_V25: Pré-calcule toutes les positions spring par frame.
    Retourne un dict {clip_id → {frame_idx → (x, y, scale, alpha)}}.
    Utile pour les exports haute résolution où on veut éviter de recalculer.

    Usage :
        positions = precompute_spring_positions(word_clips, fps=30)
        for frame_idx in range(total_frames):
            t = frame_idx / fps
            for i, c in enumerate(word_clips):
                x, y, scale, alpha = positions.get(i, {}).get(frame_idx, (0,0,1,0))
    """
    positions = {}
    for i, c in enumerate(clips):
        clip_positions = {}
        # Seuls les frames actifs
        start_frame = max(0, int(c.t_start * fps))
        end_frame   = int(c.t_end * fps) + 1
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