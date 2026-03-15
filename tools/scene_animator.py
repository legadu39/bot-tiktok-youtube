# -*- coding: utf-8 -*-
# NEXUS SCENE ANIMATOR — MASTER V22
# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22: Refonte architecturale complète.
# V9 → V22 : passage de la boucle rigide au "Timeline Engine".
#
# Nouveaux paradigmes V22 :
#   1. EasingLibrary     — Arsenal complet de courbes (Bézier, Spring, Expo)
#   2. SpringPhysics     — Oscillateur amorti véritable (formule physique exacte)
#   3. Système d'Effets  — EffectContinuousZoom / EffectSpringOvershoot / EffectWiggle
#   4. TimelineObject    — Objet vidéo auto-conscient de son état à t exact
#   5. TimelineEngine    — Compositeur temporel avec overlapping contrôlé
#   6. SmartLayoutManager— Détection collision + ajustement auto taille/wrapping
#   7. SceneAnimator     — API publique V22 (rétrocompatible avec V9)
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import math
import os
import random
import tempfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoClip
    MOVIEPY_OK = True
except ImportError:
    MOVIEPY_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 1 : EasingLibrary
# Toutes les courbes dans une classe statique unique. Un seul import suffit.
# ═══════════════════════════════════════════════════════════════════════════════

class EasingLibrary:
    """
    Arsenal complet de courbes d'accélération.
    Chaque méthode : p ∈ [0,1] → valeur ∈ [0,1] (sauf ease_out_back qui peut dépasser).
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
        """Accélération et décélération sinusoïdale — idéale pour le zoom global."""
        p = max(0.0, min(1.0, p))
        return -(math.cos(math.pi * p) - 1.0) / 2.0

    @staticmethod
    def ease_in_expo(p: float) -> float:
        """Départ quasi-nul puis explosion — sorties en swipe-up."""
        p = max(0.0, min(1.0, p))
        return 0.0 if p == 0.0 else pow(2.0, 10.0 * (p - 1.0))

    @staticmethod
    def ease_out_expo(p: float) -> float:
        """Décélération exponentielle — arrêt très précis."""
        p = max(0.0, min(1.0, p))
        return 1.0 if p == 1.0 else 1.0 - pow(2.0, -10.0 * p)

    @staticmethod
    def ease_out_back(p: float, overshoot: float = 1.70158) -> float:
        """
        Dépasse la cible puis revient — 'snap & bounce'.
        overshoot=1.70 → discret ; overshoot=2.5 → prononcé.
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


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 2 : SpringPhysics
# Oscillateur harmonique amorti — formule mathématique exacte.
# Remplace les courbes piecewise de la V21.
# ═══════════════════════════════════════════════════════════════════════════════

class SpringPhysics:
    """
    ARCHITECTURE_MASTER_V22 : Oscillateur harmonique amorti réel.

    Paramètres clés :
      stiffness (k) : rigidité du ressort [100-1000]. Plus haut = plus rapide.
      damping   (c) : coefficient d'amortissement [0 = oscillation infinie].

    Formule complète (sous-amorti ζ < 1) :
      ω₀   = √k
      ζ    = c / (2·ω₀)
      ω_d  = ω₀ · √(1 - ζ²)
      x(t) = 1 - e^(−ζω₀t) · [cos(ω_d·t) + (ζ/√(1-ζ²)) · sin(ω_d·t)]

    Preset "REFERENCE" (correspond au reverse-engineering de la vidéo) :
      stiffness=625, damping=25 → ζ≈0.50, 15.8% overshoot, settle≈200ms
    """

    def __init__(self, stiffness: float = 625.0, damping: float = 25.0):
        self.k = stiffness
        self.c = damping
        self.omega0   = math.sqrt(max(stiffness, 1e-6))
        self.zeta     = damping / (2.0 * self.omega0)
        self._mode    = self._classify()

        if self._mode == "under":
            self.omega_d = self.omega0 * math.sqrt(max(1.0 - self.zeta ** 2, 1e-12))
            self._sin_coeff = self.zeta / math.sqrt(max(1.0 - self.zeta ** 2, 1e-12))
        elif self._mode == "over":
            sq = math.sqrt(max(self.zeta ** 2 - 1.0, 1e-12))
            self._r1 = self.omega0 * (-self.zeta + sq)
            self._r2 = self.omega0 * (-self.zeta - sq)

    def _classify(self) -> str:
        if self.zeta < 1.0 - 1e-6:  return "under"
        if self.zeta > 1.0 + 1e-6:  return "over"
        return "critical"

    def value(self, t: float) -> float:
        """Retourne la position normalisée x(t) ∈ [0, 1+overshoot]."""
        t = max(0.0, t)
        if self._mode == "under":
            env = math.exp(-self.zeta * self.omega0 * t)
            return 1.0 - env * (math.cos(self.omega_d * t)
                                + self._sin_coeff * math.sin(self.omega_d * t))
        elif self._mode == "critical":
            env = math.exp(-self.omega0 * t)
            return 1.0 - env * (1.0 + self.omega0 * t)
        else:  # over
            r1, r2 = self._r1, self._r2
            denom = r2 - r1 if abs(r2 - r1) > 1e-12 else 1e-12
            return 1.0 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / denom

    def clamped(self, t: float) -> float:
        """Valeur clampée [0, 1] — utile pour l'opacité."""
        return max(0.0, min(1.0, self.value(t)))

    # ── Presets utiles ──────────────────────────────────────────────────────
    @classmethod
    def reference_pop(cls) -> "SpringPhysics":
        """Preset vidéo référence : 15% overshoot, settle ≈200ms."""
        return cls(stiffness=625, damping=25)

    @classmethod
    def gentle(cls) -> "SpringPhysics":
        """Transition douce, sans overshoot visible (ζ≈0.85)."""
        return cls(stiffness=400, damping=34)

    @classmethod
    def snappy(cls) -> "SpringPhysics":
        """Impact rapide et ferme (ζ≈0.45, settle ≈150ms)."""
        return cls(stiffness=900, damping=27)


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 3 : Système d'Effets Modulaires
# Chaque effet est une classe indépendante avec apply(frame, t, ...) -> frame.
# ═══════════════════════════════════════════════════════════════════════════════

class EffectBase:
    """Classe de base abstraite pour tous les effets V22."""
    def apply(self, frame: np.ndarray, t: float, **kwargs) -> np.ndarray:
        raise NotImplementedError


class EffectContinuousZoom(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 — EFFET CONTINU DE ZOOM.
    Applique un zoom progressif sur toute la durée de la vidéo.
    Paramétré sur scale_start → scale_end avec courbe easing au choix.

    Reverse-engineering référence :
      - Zoom 1.00 → 1.04 sur la durée totale, ease_in_out_sine.
      - Centré au milieu du frame pour éviter les bords noirs.
    """

    def __init__(
        self,
        duration:    float,
        scale_start: float = 1.00,
        scale_end:   float = 1.04,
        easing:      str   = "sine",   # "sine" | "linear" | "cubic"
    ):
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
    """
    ARCHITECTURE_MASTER_V22 — EFFET SPRING OVERSHOOT.
    Calcule scale + position Y pour une apparition avec rebond physique.

    Retourne un dict d'état (pas un frame directement — utilisé par TimelineEngine).
    apply() sur un numpy array applique la mise à l'échelle.

    Reverse-engineering référence :
      - Phase entrée : scale 0%→115%→100%, Y +15px→0, opacity 0→1, 200ms total.
      - Courbe : SpringPhysics.reference_pop() (ζ≈0.50, stiffness=625, damping=25).
    """

    def __init__(
        self,
        spring:      SpringPhysics  = None,
        slide_px:    int            = 15,    # décalage Y initial (pixels)
    ):
        self.spring   = spring or SpringPhysics.reference_pop()
        self.slide_px = slide_px

    def state_at(self, t_elapsed: float) -> dict:
        """Retourne {scale, alpha, y_offset} à t_elapsed secondes depuis l'apparition."""
        raw   = self.spring.value(t_elapsed)
        alpha = self.spring.clamped(t_elapsed)
        scale = max(0.0, raw)
        # y_offset décroissant : au départ +slide_px, à stabilisation 0
        y_off = int(self.slide_px * max(0.0, 1.0 - alpha))
        return {"scale": scale, "alpha": alpha, "y_offset": y_off}

    def apply(self, frame: np.ndarray, t: float, **_) -> np.ndarray:
        """Applique le scale spring à un frame (usage direct pour preview)."""
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
    """
    ARCHITECTURE_MASTER_V22 — EFFET WIGGLE (Tremblement Organique).
    Oscillation sinusoïdale à fréquences incommensurables (π, e) →
    aspect organique sans aléatoire pur.

    Paramètres :
      frequency : fréquence principale (Hz). Défaut 8Hz → vibration perceptible.
      amplitude : amplitude max en pixels.
      decay     : constante de décroissance exponentielle.
                  decay=5 → atténuation en ~200ms.

    Reverse-engineering référence :
      - Wiggle sur les mots-clés, amplitude=5px, decay=5, fréquence 8Hz.
      - Actif 200ms post-apparition puis s'arrête.
    """

    def __init__(
        self,
        frequency: float = 8.0,
        amplitude: float = 5.0,
        decay:     float = 5.0,
        active_ms: float = 200.0,
    ):
        self.freq      = frequency
        self.amp       = amplitude
        self.decay     = decay
        self.active_s  = active_ms / 1000.0

    def offset(self, t_elapsed: float) -> Tuple[int, int]:
        """
        Retourne (dx, dy) de tremblement déterministe.
        Fréquences X=freq*π, Y=freq*e pour éviter la synchronisation.
        """
        if t_elapsed >= self.active_s or t_elapsed < 0.0:
            return 0, 0
        envelope = math.exp(-self.decay * t_elapsed) * (1.0 - t_elapsed / self.active_s)
        dx = math.sin(t_elapsed * self.freq * math.pi) * self.amp * envelope
        dy = math.cos(t_elapsed * self.freq * math.e)  * self.amp * envelope
        return int(round(dx)), int(round(dy))

    def apply(self, frame: np.ndarray, t: float, t_birth: float = 0.0, **_) -> np.ndarray:
        """Applique le wiggle comme translation — retourne le frame décalé."""
        dx, dy = self.offset(t - t_birth)
        if dx == 0 and dy == 0:
            return frame
        h, w = frame.shape[:2]
        result = np.zeros_like(frame)
        # Décalage par roll (simple mais efficace pour de petites valeurs)
        src = np.roll(np.roll(frame, dy, axis=0), dx, axis=1)
        result[:h, :w] = src[:h, :w]
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 4 : TimelineObject & TimelineEngine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TimelineObject:
    """
    ARCHITECTURE_MASTER_V22 : Objet vidéo conscient de son cycle de vie complet.

    Champs :
      t_start   : instant d'apparition (secondes)
      t_end     : instant de disparition
      z_index   : ordre de composition (plus grand = devant)
      render_fn : render_fn(t) -> np.ndarray | None  (RGBA ou RGB)
      pos_fn    : pos_fn(t) -> (x, y)                (position coin supérieur gauche)
      alpha_fn  : alpha_fn(t) -> float ∈ [0,1]
      effects   : liste d'EffectBase appliqués en séquence
    """
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
        """Retourne None si inactif, sinon dict avec frame, pos, alpha."""
        if not self.is_active(t):
            return None
        frame = self.render_fn(t)
        if frame is None:
            return None
        # Applique les effets en séquence
        for eff in self.effects:
            frame = eff.apply(frame, t, t_birth=self.t_start)
        return {
            "frame": frame,
            "pos":   self.pos_fn(t),
            "alpha": self.alpha_fn(t),
        }


class TimelineEngine:
    """
    ARCHITECTURE_MASTER_V22 : Moteur de timeline temporelle.

    Remplace la boucle naïve sur les mots. Chaque TimelineObject peut :
      - Se chevaucher librement avec d'autres (overlapping contrôlé par z_index).
      - Connaître son état à t exact (position, scale, alpha, effets).
      - Être composité en ordre z correctement.

    Usage :
        engine = TimelineEngine(width=1080, height=1920)
        engine.add(obj)
        frame = engine.render_frame(t, base_frame)
    """

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
        """Retourne les objets actifs à t, triés par z_index."""
        return sorted(
            [o for o in self._objects if o.is_active(t)],
            key=lambda o: o.z_index
        )

    def render_frame(self, t: float, base_frame: np.ndarray) -> np.ndarray:
        """
        ARCHITECTURE_MASTER_V22 : Composition principale.
        Composite tous les objets actifs sur base_frame dans l'ordre z.
        """
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

            # Clipping aux bords du canvas
            y0s = max(0, -py);        y0d = max(0, py)
            x0s = max(0, -px);        x0d = max(0, px)
            y1s = min(ph, h_c - py);  y1d = min(h_c, py + ph)
            x1s = min(pw, w_c - px);  x1d = min(w_c, px + pw)

            if y1s <= y0s or x1s <= x0s:
                continue

            patch_sl = patch[y0s:y1s, x0s:x1s]
            bg_sl    = canvas[y0d:y1d, x0d:x1d]

            # Gestion alpha RGBA
            if patch_sl.ndim == 3 and patch_sl.shape[2] == 4:
                fg_a   = patch_sl[:, :, 3:4].astype(np.float32) / 255.0 * alpha
                fg_rgb = patch_sl[:, :, :3].astype(np.float32)
            else:
                fg_a   = np.full((*patch_sl.shape[:2], 1), alpha, dtype=np.float32)
                fg_rgb = patch_sl.astype(np.float32)

            canvas[y0d:y1d, x0d:x1d] = (bg_sl * (1.0 - fg_a) + fg_rgb * fg_a)

        return np.clip(canvas, 0, 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 5 : SmartLayoutManager
# ═══════════════════════════════════════════════════════════════════════════════

class SmartLayoutManager:
    """
    ARCHITECTURE_MASTER_V22 : Gestionnaire d'espace intelligent.

    Fonctions :
      1. Détection collision entre rectangles.
      2. Réduction automatique de fontsize si le texte dépasse la zone sûre.
      3. Calcul de layout vertical centré pour N éléments.
      4. Retour à la ligne automatique si texte trop large.

    Zone sûre (safe_zone) : rectangle dans lequel tous les éléments doivent tenir.
    """

    def __init__(
        self,
        canvas_w:   int,
        canvas_h:   int,
        safe_left:  int = 80,
        safe_right: int = 80,
        safe_top:   int = 200,
        safe_bottom: int = 350,
    ):
        self.W = canvas_w
        self.H = canvas_h
        self.safe_x1 = safe_left
        self.safe_y1 = safe_top
        self.safe_x2 = canvas_w - safe_right
        self.safe_y2 = canvas_h - safe_bottom
        self.safe_w  = self.safe_x2 - self.safe_x1
        self.safe_h  = self.safe_y2 - self.safe_y1

    def fit_fontsize(
        self,
        text:     str,
        font_fn:  Callable,    # font_fn(size) -> PIL font
        max_size: int,
        min_size: int = 30,
    ) -> int:
        """
        ARCHITECTURE_MASTER_V22 : Réduit fontsize jusqu'à ce que le texte
        tienne dans la largeur sûre. Retourne le fontsize optimal.
        """
        size = max_size
        while size >= min_size:
            try:
                font = font_fn(size)
                dummy = Image.new("RGBA", (1, 1))
                d     = ImageDraw.Draw(dummy)
                bbox  = d.textbbox((0, 0), text, font=font)
                tw    = bbox[2] - bbox[0]
                if tw <= self.safe_w:
                    return size
            except Exception:
                pass
            size -= 4
        return min_size

    def collides(
        self,
        rect_a: Tuple[int, int, int, int],   # (x, y, w, h)
        rect_b: Tuple[int, int, int, int],
        margin: int = 10,
    ) -> bool:
        ax, ay, aw, ah = rect_a
        bx, by, bw, bh = rect_b
        return not (
            ax + aw + margin < bx or
            bx + bw + margin < ax or
            ay + ah + margin < by or
            by + bh + margin < ay
        )

    def resolve_overlaps(
        self,
        rects: List[Tuple[int, int, int, int]],   # [(x, y, w, h), ...]
        gap:   int = 20,
    ) -> List[Tuple[int, int, int, int]]:
        """
        ARCHITECTURE_MASTER_V22 : Déplace les rectangles vers le bas jusqu'à
        résoudre toutes les collisions. Simple pass descendant.
        """
        resolved = list(rects)
        for i in range(1, len(resolved)):
            for j in range(i):
                while self.collides(resolved[j], resolved[i]):
                    x, y, w, h = resolved[i]
                    resolved[i] = (x, y + gap, w, h)
        return resolved

    def vertical_center_layout(
        self,
        heights:   List[int],
        gap:       int = 20,
        cy_anchor: int = None,
    ) -> List[int]:
        """
        ARCHITECTURE_MASTER_V22 : Retourne les positions Y pour N éléments
        empilés verticalement centrés autour de cy_anchor.
        """
        cy = cy_anchor if cy_anchor is not None else self.H // 2
        total_h = sum(heights) + gap * (len(heights) - 1)
        start_y = cy - total_h // 2
        ys = []
        y  = start_y
        for h in heights:
            ys.append(y)
            y += h + gap
        return ys

    def wrap_text(
        self,
        text:    str,
        font_fn: Callable,
        size:    int,
        max_w:   int = None,
    ) -> List[str]:
        """
        ARCHITECTURE_MASTER_V22 : Retour à la ligne automatique.
        Coupe le texte en lignes ne dépassant pas max_w pixels.
        """
        max_w  = max_w or self.safe_w
        words  = text.split()
        lines  = []
        current = []
        try:
            font  = font_fn(size)
            dummy = Image.new("RGBA", (1, 1))
            d     = ImageDraw.Draw(dummy)

            for word in words:
                test = " ".join(current + [word])
                bbox = d.textbbox((0, 0), test, font=font)
                if bbox[2] - bbox[0] > max_w and current:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))
        except Exception:
            lines = [text]
        return lines or [text]


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 6 : Contexte Scène (rétrocompatibilité V9)
# ═══════════════════════════════════════════════════════════════════════════════

class SceneContext:
    def __init__(self):
        self.last_motion       = "NONE"
        self.consecutive_count = 0
        self.scene_index       = 0

    def update(self, motion_type: str):
        self.scene_index += 1
        if self.last_motion == motion_type:
            self.consecutive_count += 1
        else:
            self.last_motion       = motion_type
            self.consecutive_count = 1


# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V22 — BLOC 7 : SceneAnimator V22
# API publique — rétrocompatible avec V9, enrichie des nouvelles primitives.
# ═══════════════════════════════════════════════════════════════════════════════

class SceneAnimator:
    """
    NEXUS Scene Animator V22 — Timeline Engine + Modular Effects.

    API publique maintenue (rétrocompatible V9) :
      create_background(), create_dynamic_clip(), create_scene(),
      apply_global_slowzoom(), apply_micro_zoom_continuous(),
      create_slide_transition(), create_fade_transition(),
      create_animated_repeater_clip(), create_ui_price_card(),
      create_underline_draw_frame()

    Nouveautés V22 :
      make_timeline_engine()        → TimelineEngine configuré
      create_image_card_clip()      → Carte produit avec coins arrondis
      create_price_comparison_clip()→ Blocs prix animés avec ligne pointillée
      apply_effect_chain()          → Chaîne d'effets sur un clip moviepy
    """

    WHITE_BG_COLOR = (255, 255, 255)
    CREAM_BG_COLOR = (245, 245, 247)
    SHADOW_COLOR   = (200, 200, 205, 80)

    # Easing aliasé depuis la librairie
    _ease = EasingLibrary

    def __init__(self, width: int = 1080, height: int = 1920):
        self.W        = width
        self.H        = height
        self.temp_dir = tempfile.gettempdir()

        # ARCHITECTURE_MASTER_V22 : Layout manager par défaut
        self.layout = SmartLayoutManager(
            canvas_w    = width,
            canvas_h    = height,
            safe_left   = 80,
            safe_right  = 80,
            safe_top    = 200,
            safe_bottom = 350,
        )

    # ── Backward-compat easing aliases ──────────────────────────────────────

    @staticmethod
    def _ease_out_cubic(p):   return EasingLibrary.ease_out_cubic(p)
    @staticmethod
    def _ease_in_out_sine(p): return EasingLibrary.ease_in_out_sine(p)
    @staticmethod
    def _ease_in_expo(p):     return EasingLibrary.ease_in_expo(p)
    @staticmethod
    def _ease_out_expo(p):    return EasingLibrary.ease_out_expo(p)
    @staticmethod
    def _ease_out_back(p, overshoot=1.70158):
        return EasingLibrary.ease_out_back(p, overshoot)
    @staticmethod
    def _ease_in_out_spring(p): return EasingLibrary.ease_in_out_cubic(p)
    @staticmethod
    def _ease_out(p):         return EasingLibrary.ease_out_cubic(p)

    # ── Helpers internes ─────────────────────────────────────────────────────

    def _get_interest_center(self, image_path: str) -> Tuple[float, float]:
        try:
            with Image.open(image_path) as img:
                small = img.resize((100, 100)).convert("L")
                arr   = np.array(small)
                h, w  = arr.shape
                best_score  = -1
                best_center = (0.5, 0.5)
                for r in range(3):
                    for c in range(3):
                        sub   = arr[r*(h//3):(r+1)*(h//3), c*(w//3):(c+1)*(w//3)]
                        score = np.std(sub)
                        if score > best_score:
                            best_score  = score
                            best_center = ((c + 0.5)/3.0, (r + 0.5)/3.0)
                return best_center
        except Exception:
            return (0.5, 0.5)

    def _determine_mood(self, keywords: str) -> str:
        k = keywords.lower()
        if any(x in k for x in ["crash","chute","danger","stop","perte","alerte","scam","urgent"]):
            return "URGENT"
        if any(x in k for x in ["profit","gain","hausse","moon","succès","argent","croissance","million"]):
            return "GROWTH"
        return "NEUTRAL"

    def _decide_motion_strategy(self, mood: str, context: SceneContext) -> str:
        if mood == "URGENT":
            return "ZOOM_IN_HARD" if context.consecutive_count < 3 else "ZOOM_IN"
        if context.last_motion in ["ZOOM_IN", "ZOOM_IN_HARD"]:
            return random.choice(["STATIC", "ZOOM_OUT"])
        if context.last_motion in ["STATIC", "ZOOM_OUT"]:
            return "ZOOM_IN"
        return "STATIC"

    # ── Fonds ───────────────────────────────────────────────────────────────

    def create_background(self, output_path: str, style: str = "white") -> str:
        color = self.WHITE_BG_COLOR if style == "white" else self.CREAM_BG_COLOR
        img   = Image.new("RGB", (self.W, self.H), color=color)
        img.save(output_path, quality=98)
        return output_path

    def create_cream_background(self, output_path: str) -> str:
        return self.create_background(output_path, style="cream")

    # ── Clip dynamique (rétrocompatible V9) ─────────────────────────────────

    def create_dynamic_clip(
        self,
        image_path,
        duration:          float      = 5.0,
        context_keywords:  str        = "",
        scene_context:     SceneContext = None,
        apply_mutation:    bool        = False,
    ):
        if not MOVIEPY_OK:
            raise ImportError("moviepy requis pour create_dynamic_clip")

        if scene_context is None:
            scene_context = SceneContext()

        working_path = self._apply_visual_mutation(str(image_path)) if apply_mutation else image_path
        if apply_mutation:
            duration += random.uniform(-0.1, 0.1)

        mood        = self._determine_mood(context_keywords)
        motion_type = self._decide_motion_strategy(mood, scene_context)
        scene_context.update(motion_type)

        tx, ty = self._get_interest_center(str(working_path))

        zoom_factors = {
            "ZOOM_IN_HARD": 1.05, "ZOOM_IN": 1.03,
            "ZOOM_OUT":     1.04, "STATIC":  1.00, "PAN_SLOW": 1.05,
        }
        zoom_factor = zoom_factors.get(motion_type, 1.02)

        try:
            img = ImageClip(str(working_path)).set_duration(duration)
        except Exception:
            img = ImageClip(str(image_path)).set_duration(duration)

        img_w, img_h = img.size
        ratio_canvas = self.W / self.H
        ratio_img    = img_w / img_h
        new_h        = self.H * zoom_factor
        new_w        = self.W * zoom_factor

        if ratio_img > ratio_canvas:
            final_h = new_h
            final_w = final_h * ratio_img
        else:
            final_w = new_w
            final_h = final_w / ratio_img

        img = (img.resize(width=int(final_w)) if final_w > final_h * ratio_img
               else img.resize(height=int(final_h)))

        xov    = img.w - self.W
        yov    = img.h - self.H
        ideal_x = (self.W / 2) - (tx * img.w)
        ideal_y = (self.H / 2) - (ty * img.h)
        focus_x = max(-xov, min(0, ideal_x))
        focus_y = max(-yov, min(0, ideal_y))
        cx      = -xov / 2
        cy      = -yov / 2
        start_x, start_y = cx, cy
        dest_x,  dest_y  = cx, cy

        if "ZOOM_IN" in motion_type:
            dest_x, dest_y = focus_x, focus_y
        elif motion_type == "ZOOM_OUT":
            start_x, start_y = focus_x, focus_y
        elif motion_type == "PAN_SLOW":
            if xov > yov:
                start_x = 0 if focus_x < cx else -xov
                dest_x  = -xov if focus_x < cx else 0
            else:
                start_y = 0
                dest_y  = -yov

        def position_func(t):
            if motion_type == "STATIC":
                return (int(cx), int(cy))
            p = t / duration
            p = (p**3 if motion_type == "ZOOM_IN_HARD"
                 else p if motion_type == "PAN_SLOW"
                 else -p * (p - 2))
            return (int(start_x + (dest_x - start_x) * p),
                    int(start_y + (dest_y - start_y) * p))

        img = img.set_position(position_func)
        return CompositeVideoClip([img], size=(self.W, self.H))

    def create_scene(
        self,
        image_path,
        duration:       float = 5.0,
        effect=None,
        resolution=None,
        apply_mutation: bool  = False,
    ):
        return self.create_dynamic_clip(image_path, duration=duration, apply_mutation=apply_mutation)

    # ── Zoom global & micro-zoom (rétrocompatibles V9) ──────────────────────

    def apply_global_slowzoom(self, clip, start_scale=1.0, end_scale=1.05):
        """V22 : délègue à EffectContinuousZoom."""
        duration = clip.duration
        effect   = EffectContinuousZoom(duration, start_scale, end_scale, "sine")
        def zoom_frame(get_frame, t):
            return effect.apply(get_frame(t), t)
        return clip.fl(zoom_frame)

    def apply_micro_zoom_continuous(self, clip, intensity: float = 0.008):
        duration = clip.duration
        def mz(get_frame, t):
            p     = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            scale = 1.0 + intensity * p
            return EffectContinuousZoom(duration, 1.0, 1.0 + intensity).apply(get_frame(t), t)
        return clip.fl(mz)

    # ── Transitions ─────────────────────────────────────────────────────────

    def create_slide_transition(
        self,
        clip_out,
        clip_in,
        transition_duration: float = 0.30,
        direction:           str   = "left",
        spring:              bool  = True,
    ):
        td = transition_duration
        vectors = {"left": (-self.W,0), "right":(self.W,0), "up":(0,-self.H), "down":(0,self.H)}
        dx, dy  = vectors.get(direction, (-self.W, 0))
        ease_in = self._ease_out_back if spring else self._ease_out_cubic

        out_clip = clip_out.set_duration(td).set_position(
            lambda t: (int(dx * self._ease_out_cubic(min(t/td, 1.0))),
                       int(dy * self._ease_out_cubic(min(t/td, 1.0))))
        )
        in_clip = clip_in.set_duration(td).set_position(
            lambda t: (int(-dx * (1.0 - ease_in(min(t/td, 1.0)))),
                       int(-dy * (1.0 - ease_in(min(t/td, 1.0)))))
        )
        return CompositeVideoClip([out_clip, in_clip], size=(self.W, self.H)).set_duration(td)

    def create_fade_transition(self, clip_out, clip_in, transition_duration=0.10):
        td = transition_duration
        def fo(get_frame, t):
            a = 1.0 - EasingLibrary.ease_in_out_sine(min(t/td, 1.0))
            return (get_frame(t).astype(np.float32) * a).astype(np.uint8)
        def fi(get_frame, t):
            a = EasingLibrary.ease_in_out_sine(min(t/td, 1.0))
            return (get_frame(t).astype(np.float32) * a).astype(np.uint8)
        return CompositeVideoClip(
            [clip_out.set_duration(td).fl(fo), clip_in.set_duration(td).fl(fi)],
            size=(self.W, self.H)
        ).set_duration(td)

    # ── Motion blur ─────────────────────────────────────────────────────────

    def apply_motion_blur(self, clip, strength=0.35, num_samples=2):
        fps = clip.fps or 30.0
        def blur(get_frame, t):
            cur = get_frame(t).astype(np.float32)
            if t == 0:
                return cur.astype(np.uint8)
            res = cur * (1.0 - strength)
            try:
                prev = get_frame(max(0, t - 1.0/fps)).astype(np.float32)
                res += prev * strength
            except Exception:
                return cur.astype(np.uint8)
            return np.clip(res, 0, 255).astype(np.uint8)
        return clip.fl(blur)

    # ── Underline animé ─────────────────────────────────────────────────────

    def create_underline_draw_frame(
        self,
        frame:     np.ndarray,
        progress:  float,
        y_pos:     int,
        x_start:   int,
        x_end:     int,
        color:     tuple = (123, 44, 191),
        thickness: int   = 6,
    ) -> np.ndarray:
        img   = Image.fromarray(frame)
        draw  = ImageDraw.Draw(img)
        eased = EasingLibrary.ease_out_expo(max(0.0, min(1.0, progress)))
        x_cur = int(x_start + (x_end - x_start) * eased)
        if x_cur > x_start:
            draw.line([(x_start, y_pos), (x_cur, y_pos)], fill=color, width=thickness)
            shadow_c = color + (80,) if len(color) == 3 else color
            draw.line([(x_start, y_pos+3), (x_cur, y_pos+3)], fill=shadow_c, width=max(1, thickness//3))
        return np.array(img)

    def should_slide_transition(self, prev_kw: str, curr_kw: str) -> bool:
        return self._determine_mood(prev_kw) != self._determine_mood(curr_kw)

    def should_fade_transition(self, prev_kw: str, curr_kw: str) -> bool:
        return not self.should_slide_transition(prev_kw, curr_kw)

    def get_slide_direction(self, scene_index: int) -> str:
        return ["left", "up", "left", "down"][scene_index % 4]

    # ── Mutation visuelle (rétrocompat V9) ──────────────────────────────────

    def _apply_visual_mutation(self, image_path: str) -> str:
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                if random.random() > 0.5:
                    img = ImageOps.mirror(img)
                for cls, delta in [(ImageEnhance.Brightness, 0.02), (ImageEnhance.Contrast, 0.02)]:
                    img = cls(img).enhance(1.0 + random.uniform(-delta, delta))
                w, h   = img.size
                margin = min(w, h) * 0.01
                img    = img.crop((margin, margin, w-margin, h-margin))
                tmp    = os.path.join(self.temp_dir, f"mut_{random.randint(10000,99999)}.jpg")
                img.save(tmp, quality=95)
                return tmp
        except Exception:
            return image_path

    # ── Badge prix neumorphique (rétrocompat V9) ─────────────────────────────

    def create_ui_price_card(
        self,
        text:         str,
        width:        int   = None,
        bg_color:     tuple = (255, 255, 255),
        accent_color: tuple = (123, 44, 191),
        font_path:    str   = None,
    ) -> np.ndarray:
        if width is None:
            width = int(self.W * 0.55)
        pad_h, pad_v, radius = 48, 32, 32
        font_size = 88
        candidates = [font_path, "Inter-ExtraBold.ttf", "Montserrat-ExtraBold.ttf",
                      "Poppins-Bold.ttf", "arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        pil_font = None
        for fp in candidates:
            if fp and os.path.exists(str(fp)):
                try:
                    pil_font = ImageFont.truetype(fp, font_size)
                    break
                except Exception:
                    continue
        if pil_font is None:
            pil_font = ImageFont.load_default()
        try:
            bbox = pil_font.getbbox(text)
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        except Exception:
            tw, th = len(text)*45, 60
        cw = min(tw + pad_h*2, width)
        ch = th + pad_v*2 + 8
        r  = min(radius, ch//2)
        canvas = Image.new("RGBA", (cw+12, ch+12), (0,0,0,0))
        draw   = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([6,6,cw+6-1,ch+6-1], radius=r, fill=(180,180,185,120))
        draw.rounded_rectangle([-2,-2,cw-2,ch-2], radius=r, fill=(255,255,255,200))
        draw.rounded_rectangle([0,0,cw-1,ch-1], radius=r,
                                fill=bg_color+(255,) if len(bg_color)==3 else bg_color)
        draw.text(((cw-tw)//2, pad_v), text, font=pil_font, fill=accent_color+(255,))
        return np.array(canvas)

    # ── Matrice répétition animée (rétrocompat V9) ──────────────────────────

    def create_repeater_matrix(
        self, element_path, cols=8, rows=14, output_path=None,
        opacity=0.12, bg_color=(255,255,255), canvas_w=None, canvas_h=None
    ) -> str:
        if output_path is None:
            output_path = os.path.join(self.temp_dir, f"rep_{random.randint(10000,99999)}.png")
        cw = canvas_w or self.W
        ch = canvas_h or self.H
        canvas  = Image.new("RGBA", (cw, ch), bg_color + (255,))
        cell_w, cell_h = cw//cols, ch//rows
        try:
            elem = Image.open(element_path).convert("RGBA")
        except Exception:
            elem = Image.new("RGBA", (20,20), (29,29,31,255))
        elem.thumbnail((int(cell_w*0.75), int(cell_h*0.75)), Image.LANCZOS)
        if opacity < 1.0:
            r, g, b, a = elem.split()
            a = a.point(lambda x: int(x * opacity))
            elem = Image.merge("RGBA", (r,g,b,a))
        for row in range(rows):
            for col in range(cols):
                ox = (cell_w//4) if row%2==1 else 0
                x  = col*cell_w + (cell_w - elem.width)//2 + ox
                y  = row*cell_h + (cell_h - elem.height)//2
                canvas.paste(elem, (x, y), mask=elem.split()[3])
        canvas.convert("RGB").save(output_path, quality=95)
        return output_path

    def create_animated_repeater_clip(
        self, element_path, duration, cols=8, rows=14, opacity=0.12, bg_color=(255,255,255)
    ):
        ow = int(self.W * 1.3)
        oh = int(self.H * 1.3)
        mp = self.create_repeater_matrix(element_path, int(cols*1.3), int(rows*1.3),
                                          opacity=opacity, bg_color=bg_color, canvas_w=ow, canvas_h=oh)
        clip = ImageClip(mp).set_duration(duration)
        xov  = ow - self.W
        yov  = oh - self.H
        def pos(t):
            ease = EasingLibrary.ease_in_out_sine(t/max(duration,1e-6))
            return (int(-xov*0.8*ease), int(-yov*0.8*ease))
        return CompositeVideoClip([clip.set_position(pos)], size=(self.W, self.H))

    # ──────────────────────────────────────────────────────────────────────────
    # ARCHITECTURE_MASTER_V22 — NOUVELLES PRIMITIVES
    # ──────────────────────────────────────────────────────────────────────────

    def make_timeline_engine(self) -> TimelineEngine:
        """ARCHITECTURE_MASTER_V22 : Crée un TimelineEngine aux dimensions de ce SceneAnimator."""
        return TimelineEngine(width=self.W, height=self.H)

    def create_image_card_clip(
        self,
        image_path:     str,
        duration:       float,
        card_w:         int   = None,
        corner_radius:  int   = 37,
        shadow_blur:    int   = 24,
        t_appear:       float = 0.0,
        spring:         SpringPhysics = None,
    ):
        """
        ARCHITECTURE_MASTER_V22 : Carte produit avec coins arrondis et ombre portée.

        Reverse-engineering référence (frame 8s) :
          - Card width ≈ 52% du canvas.
          - Fond de la carte : image originale (peut être sombre/clair).
          - Corner radius ≈ 37px (à 1080px).
          - Ombre portée : blur=24, offset-y=8, opacité 30%.
          - Apparition : spring overshoot (EffectSpringOvershoot).

        Retourne un moviepy clip (CompositeVideoClip).
        """
        if not MOVIEPY_OK:
            raise ImportError("moviepy requis")

        cw      = card_w or int(self.W * 0.52)
        sp      = spring or SpringPhysics.reference_pop()
        sp_eff  = EffectSpringOvershoot(spring=sp, slide_px=20)

        # ── Chargement et mise à l'échelle de l'image ───────────────────────
        try:
            img_pil = Image.open(image_path).convert("RGBA")
        except Exception:
            img_pil = Image.new("RGBA", (cw, cw), (30, 30, 30, 255))

        ratio = cw / img_pil.width
        ch    = int(img_pil.height * ratio)
        img_pil = img_pil.resize((cw, ch), Image.LANCZOS)

        # ── Masque coin arrondi ──────────────────────────────────────────────
        mask = Image.new("L", (cw, ch), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle([0, 0, cw-1, ch-1], radius=corner_radius, fill=255)
        img_pil.putalpha(mask)

        # ── Ombre portée ────────────────────────────────────────────────────
        shadow = Image.new("RGBA", (cw + 40, ch + 40), (0, 0, 0, 0))
        smask  = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(smask).rounded_rectangle([0,0,cw-1,ch-1], radius=corner_radius, fill=180)
        shadow.paste(Image.new("RGBA", (cw, ch), (0, 0, 0, 90)), (20, 16), mask=smask)
        shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        shadow.paste(img_pil, (10, 10), mask=img_pil.split()[3])

        card_arr = np.array(shadow)  # RGBA, taille (ch+40, cw+40)
        card_h, card_w = card_arr.shape[:2]

        cx_pos = (self.W - card_w) // 2
        cy_pos = (self.H - card_h) // 2

        def render_fn(t):
            return card_arr

        def pos_fn(t):
            elapsed = t - t_appear
            if elapsed < 0:
                return (cx_pos, self.H + 50)  # hors écran
            state = sp_eff.state_at(elapsed)
            yo    = state["y_offset"]
            return (cx_pos, cy_pos + yo)

        def alpha_fn(t):
            elapsed = t - t_appear
            if elapsed < 0:
                return 0.0
            return sp_eff.state_at(elapsed)["alpha"]

        obj = TimelineObject(
            t_start   = t_appear,
            t_end     = t_appear + duration,
            render_fn = render_fn,
            pos_fn    = pos_fn,
            alpha_fn  = alpha_fn,
            z_index   = 10,
            tag       = "image_card",
        )
        engine = self.make_timeline_engine()
        engine.add(obj)

        # ── Fond blanc base ──────────────────────────────────────────────────
        base = np.full((self.H, self.W, 3), 255, dtype=np.uint8)

        zoom_fx = EffectContinuousZoom(duration=duration, scale_start=1.0, scale_end=1.03)

        def make_frame(t):
            f = engine.render_frame(t, base.copy())
            return zoom_fx.apply(f, t)

        clip = VideoClip(make_frame, duration=duration).set_fps(30)
        return clip

    def create_price_comparison_clip(
        self,
        prices:    List[Tuple[str, Tuple[int,int,int]]],  # [("79$", (R,G,B)), ...]
        duration:  float,
        block_size: int  = 140,
        t_appear:  float = 0.0,
    ):
        """
        ARCHITECTURE_MASTER_V22 : Blocs prix colorés animés.

        Reverse-engineering référence (frame 16s) :
          - 3 blocs (vert, rouge, bleu) ≈ 140×140px à 1080px.
          - Prix affiché en gris-noir au-dessus de chaque bloc.
          - Ligne pointillée horizontale au centre.
          - Chaque bloc apparaît en spring avec stagger de 80ms.
          - Les blocs sont à des hauteurs légèrement différentes (±30px).

        prices : liste de (label, (R,G,B)) — maximum 5 éléments.
        """
        if not MOVIEPY_OK:
            raise ImportError("moviepy requis")

        n     = len(prices)
        STAGGER = 0.08  # 80ms entre chaque bloc

        # ── Positions Y avec décalage alterné ───────────────────────────────
        cy  = self.H // 2
        offsets_y = [0, -30, 30, -20, 20][:n]

        # ── Espacement X centré ─────────────────────────────────────────────
        gap_x = block_size + 60
        total_x  = (n - 1) * gap_x
        start_x  = (self.W - total_x) // 2

        # ── Rendu d'un bloc ─────────────────────────────────────────────────
        def render_block(label: str, color: Tuple) -> np.ndarray:
            bs     = block_size
            pad_shadow = 20
            total  = bs + pad_shadow * 2
            canvas = Image.new("RGBA", (total, total + 40), (0,0,0,0))
            draw   = ImageDraw.Draw(canvas)

            # Ombre
            smask = Image.new("L", (bs, bs), 0)
            ImageDraw.Draw(smask).rounded_rectangle([0,0,bs-1,bs-1], radius=24, fill=120)
            shadow_img = Image.new("RGBA", (bs, bs), color + (80,))
            shadow_full= Image.new("RGBA", (total, total), (0,0,0,0))
            shadow_full.paste(shadow_img, (pad_shadow, pad_shadow), mask=smask)
            shadow_full = shadow_full.filter(ImageFilter.GaussianBlur(14))
            canvas.paste(shadow_full, (0, 4), mask=shadow_full.split()[3])

            # Bloc coloré
            block = Image.new("RGBA", (bs, bs), color + (255,))
            bmask = Image.new("L", (bs, bs), 0)
            ImageDraw.Draw(bmask).rounded_rectangle([0,0,bs-1,bs-1], radius=24, fill=255)
            block.putalpha(bmask)
            canvas.paste(block, (pad_shadow, pad_shadow), mask=block.split()[3])

            return np.array(canvas)

        def render_label(label: str, fs: int = 48) -> np.ndarray:
            candidates = ["Inter-Bold.ttf","Montserrat-Bold.ttf","DejaVuSans-Bold.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
            font = ImageFont.load_default()
            for fp in candidates:
                if os.path.exists(fp):
                    try:
                        font = ImageFont.truetype(fp, fs)
                        break
                    except Exception:
                        pass
            dummy = Image.new("RGBA",(1,1))
            d     = ImageDraw.Draw(dummy)
            try:
                bbox = d.textbbox((0,0), label, font=font)
                tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            except Exception:
                tw, th = len(label)*28, 40
            canvas = Image.new("RGBA", (tw+20, th+10), (0,0,0,0))
            ImageDraw.Draw(canvas).text((10,5), label, font=font, fill=(30,30,30,255))
            return np.array(canvas)

        # ── Pré-render tous les éléments ────────────────────────────────────
        block_arrays = [render_block(lbl, col) for lbl, col in prices]
        label_arrays = [render_label(lbl) for lbl, _ in prices]
        springs      = [SpringPhysics.reference_pop() for _ in prices]
        sp_effs      = [EffectSpringOvershoot(spring=s, slide_px=25) for s in springs]

        base   = np.full((self.H, self.W, 3), 255, dtype=np.uint8)
        engine = self.make_timeline_engine()

        for i in range(n):
            t_birth  = t_appear + i * STAGGER
            bx       = start_x + i * gap_x
            by       = cy + offsets_y[i] - block_size // 2
            barr     = block_arrays[i]
            larr     = label_arrays[i]
            sp_eff   = sp_effs[i]

            bh, bw = barr.shape[:2]
            lh, lw = larr.shape[:2]

            lx = bx + (block_size - lw) // 2
            ly = by - lh - 8

            idx = i  # closure capture

            def make_block_render(arr):
                def fn(t): return arr
                return fn

            def make_alpha(t_b, eff):
                def fn(t):
                    e = t - t_b
                    return 0.0 if e < 0 else eff.state_at(e)["alpha"]
                return fn

            def make_pos(bx_val, by_val, t_b, eff):
                def fn(t):
                    e = t - t_b
                    if e < 0: return (bx_val, by_val + 60)
                    yo = eff.state_at(e)["y_offset"]
                    return (bx_val, by_val + yo)
                return fn

            engine.add(TimelineObject(
                t_start=t_appear, t_end=t_appear+duration,
                render_fn=make_block_render(barr),
                pos_fn=make_pos(bx - 20, by, t_birth, sp_eff),
                alpha_fn=make_alpha(t_birth, sp_eff),
                z_index=10,
            ))
            engine.add(TimelineObject(
                t_start=t_appear, t_end=t_appear+duration,
                render_fn=make_block_render(larr),
                pos_fn=make_pos(lx, ly, t_birth, sp_eff),
                alpha_fn=make_alpha(t_birth, sp_eff),
                z_index=11,
            ))

        # ── Ligne pointillée ────────────────────────────────────────────────
        dash_arr = self._make_dash_line(self.W, 4)
        dash_y   = cy - 2

        engine.add(TimelineObject(
            t_start   = t_appear + (n-1)*STAGGER + 0.15,
            t_end     = t_appear + duration,
            render_fn = lambda t: dash_arr,
            pos_fn    = lambda t: (0, dash_y),
            alpha_fn  = lambda t: min(1.0, (t - (t_appear + (n-1)*STAGGER + 0.15)) / 0.2),
            z_index   = 5,
        ))

        def make_frame(t):
            return engine.render_frame(t, base.copy())

        return VideoClip(make_frame, duration=duration).set_fps(30)

    def _make_dash_line(self, width: int, height: int = 4,
                         dash: int = 20, gap: int = 12,
                         color=(180,180,185)) -> np.ndarray:
        """ARCHITECTURE_MASTER_V22 : Ligne pointillée horizontale."""
        arr  = np.zeros((height, width, 4), dtype=np.uint8)
        x    = 0
        draw_dash = True
        while x < width:
            end = min(x + (dash if draw_dash else gap), width)
            if draw_dash:
                arr[:, x:end, :3] = color
                arr[:, x:end, 3]  = 200
            x += (dash if draw_dash else gap)
            draw_dash = not draw_dash
        return arr

    def apply_effect_chain(self, clip, effects: List[EffectBase]):
        """
        ARCHITECTURE_MASTER_V22 : Applique une chaîne d'effets V22 sur un clip moviepy.
        Les effets sont appliqués dans l'ordre de la liste.
        """
        def chained(get_frame, t):
            frame = get_frame(t)
            for eff in effects:
                frame = eff.apply(frame, t)
            return frame
        return clip.fl(chained)