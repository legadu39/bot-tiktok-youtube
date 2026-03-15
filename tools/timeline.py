# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Timeline Engine — cœur du moteur vidéo.
#
# PARADIGME CLÉ (rupture avec V9) :
#   V9 : boucle simple sur des mots → rigide, pas d'overlapping
#   V22 : chaque objet connaît son état à t exact → overlapping contrôlé
#
# Un TimelineObject sait :
#   1. Quand il est actif (t_start ≤ t ≤ t_end)
#   2. Où se positionner (pos_fn(t) → (x,y))
#   3. Quelle est son opacité (alpha_fn(t) → [0,1])
#   4. Quel frame rendre (render_fn(t) → np.ndarray)
#   5. Quels effets appliquer (liste d'EffectBase)
#   6. Son ordre de composition (z_index)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple
import numpy as np

from .effects import EffectBase


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — TimelineObject
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TimelineObject:
    """
    ARCHITECTURE_MASTER_V22 : Objet vidéo auto-conscient.

    Champs obligatoires :
        t_start, t_end  : fenêtre d'activité (secondes)
        render_fn       : render_fn(t) → np.ndarray (RGBA ou RGB)

    Champs optionnels :
        pos_fn          : pos_fn(t) → (x, y) coin supérieur gauche
        alpha_fn        : alpha_fn(t) → float ∈ [0,1]
        z_index         : ordre de composition (plus grand = devant)
        effects         : liste d'EffectBase appliqués EN SÉQUENCE
        tag             : identifiant textuel pour debug/filtrage

    NOTE sur le hard-cut (référence) :
        Pour simuler le hard-cut de la référence, t_end est simplement
        l'instant exact de la prochaine apparition. Pas d'alpha_fn décroissant.
    """

    t_start:   float
    t_end:     float
    render_fn: Callable

    pos_fn:    Callable                = field(default=lambda t: (0, 0))
    alpha_fn:  Callable                = field(default=lambda t: 1.0)
    z_index:   int                     = 0
    effects:   List[EffectBase]        = field(default_factory=list)
    tag:       str                     = ""

    def is_active(self, t: float) -> bool:
        return self.t_start <= t < self.t_end   # NOTE: < t_end = hard cut exact

    def get_state(self, t: float) -> Optional[dict]:
        """
        Retourne {frame, pos, alpha} à t, ou None si inactif.
        Les effets sont appliqués dans l'ordre de la liste.
        """
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
            "alpha": float(self.alpha_fn(t)),
        }


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — TimelineEngine
# ══════════════════════════════════════════════════════════════════════════════

class TimelineEngine:
    """
    ARCHITECTURE_MASTER_V22 : Compositeur temporel avec overlapping contrôlé.

    Fonctionnement :
        1. Tous les TimelineObject sont stockés dans _objects.
        2. À render_frame(t), on filtre les objets actifs (is_active(t)).
        3. On les trie par z_index (croissant = derrière).
        4. On composite chacun sur le canvas via alpha-blending.

    Avantage sur V9 :
        - Deux objets peuvent se chevaucher temporellement sans conflit.
        - Le z_index gère la profondeur → plus besoin de séquencer manuellement.
        - Chaque objet a son propre t_start/t_end → la timeline est déclarative.

    Usage :
        engine = TimelineEngine(1080, 1920)
        engine.add(TimelineObject(t_start=0.5, t_end=1.2, render_fn=my_render, ...))
        frame  = engine.render_frame(0.8, white_base)
    """

    def __init__(self, width: int = 1080, height: int = 1920):
        self.W = width
        self.H = height
        self._objects: List[TimelineObject] = []

    # ── API publique ──────────────────────────────────────────────────────────

    def add(self, obj: TimelineObject) -> "TimelineEngine":
        self._objects.append(obj)
        return self

    def add_all(self, objs: List[TimelineObject]) -> "TimelineEngine":
        self._objects.extend(objs)
        return self

    def clear(self) -> None:
        self._objects.clear()

    def active_at(self, t: float) -> List[TimelineObject]:
        return sorted(
            [o for o in self._objects if o.is_active(t)],
            key=lambda o: o.z_index,
        )

    def objects_by_tag(self, tag: str) -> List[TimelineObject]:
        return [o for o in self._objects if o.tag == tag]

    # ── Rendu ─────────────────────────────────────────────────────────────────

    def render_frame(self, t: float, base_frame: np.ndarray) -> np.ndarray:
        """
        ARCHITECTURE_MASTER_V22 : Composition principale.

        Algorithme :
            canvas = base_frame (fond blanc ou image)
            pour chaque objet actif (ordre z_index) :
                récupérer frame + position + alpha
                alpha-blend sur canvas (Porter-Duff over, optimisé numpy)
        """
        canvas   = base_frame.astype(np.float32)
        h_c, w_c = canvas.shape[:2]

        for obj in self.active_at(t):
            state = obj.get_state(t)
            if state is None:
                continue

            patch  = state["frame"]
            px, py = state["pos"]
            alpha  = state["alpha"]

            if alpha < 0.004 or patch is None:
                continue

            ph, pw = patch.shape[:2]

            # ── Clipping aux bords du canvas ──────────────────────────────
            y0s = max(0, -py);        y0d = max(0, py)
            x0s = max(0, -px);        x0d = max(0, px)
            y1s = min(ph, h_c - py);  y1d = min(h_c, py + ph)
            x1s = min(pw, w_c - px);  x1d = min(w_c, px + pw)

            if y1s <= y0s or x1s <= x0s:
                continue

            patch_sl = patch[y0s:y1s, x0s:x1s]
            bg_sl    = canvas[y0d:y1d, x0d:x1d]

            # ── Alpha-blending (Porter-Duff Over) ──────────────────────────
            if patch_sl.ndim == 3 and patch_sl.shape[2] == 4:
                fg_a   = patch_sl[:, :, 3:4].astype(np.float32) / 255.0 * alpha
                fg_rgb = patch_sl[:, :, :3].astype(np.float32)
            else:
                fg_a   = np.full((*patch_sl.shape[:2], 1), alpha, dtype=np.float32)
                fg_rgb = patch_sl.astype(np.float32)

            canvas[y0d:y1d, x0d:x1d] = bg_sl * (1.0 - fg_a) + fg_rgb * fg_a

        return np.clip(canvas, 0, 255).astype(np.uint8)

    # ── Helpers de construction ───────────────────────────────────────────────

    def make_static_image_object(
        self,
        image_array: np.ndarray,
        t_start:     float,
        t_end:       float,
        x:           int,
        y:           int,
        alpha:       float = 1.0,
        z_index:     int   = 0,
        tag:         str   = "",
    ) -> TimelineObject:
        """
        ARCHITECTURE_MASTER_V22 : Raccourci pour un objet image statique.
        Utile pour les fonds, badges, icônes.
        """
        arr = image_array
        return TimelineObject(
            t_start   = t_start,
            t_end     = t_end,
            render_fn = lambda t, _arr=arr: _arr,
            pos_fn    = lambda t, _x=x, _y=y: (_x, _y),
            alpha_fn  = lambda t, _a=alpha: _a,
            z_index   = z_index,
            tag       = tag,
        )

    def make_spring_entry_object(
        self,
        image_array: np.ndarray,
        t_start:     float,
        t_end:       float,
        x:           int,
        y:           int,
        spring,
        slide_px:    int = 8,
        z_index:     int = 10,
        tag:         str = "",
    ) -> TimelineObject:
        """
        ARCHITECTURE_MASTER_V22 : Raccourci pour objet avec entrée spring.
        C'est le pattern de la RÉFÉRENCE pour tout élément textuel ou card.

        slide_px=8 : valeur mesurée pixel-exact dans la vidéo référence.
        """
        arr = image_array

        def pos_fn(t: float) -> Tuple[int, int]:
            elapsed = t - t_start
            if elapsed < 0:
                return (x, y + 60)  # hors écran (sécurité)
            raw = spring.value(elapsed)
            alpha = spring.clamped(elapsed)
            y_off = int(slide_px * max(0.0, 1.0 - alpha))
            return (x, y + y_off)

        def alpha_fn(t: float) -> float:
            elapsed = t - t_start
            if elapsed < 0:
                return 0.0
            return spring.clamped(elapsed)

        return TimelineObject(
            t_start   = t_start,
            t_end     = t_end,
            render_fn = lambda t, _arr=arr: _arr,
            pos_fn    = pos_fn,
            alpha_fn  = alpha_fn,
            z_index   = z_index,
            tag       = tag,
        )