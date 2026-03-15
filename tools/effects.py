# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Système d'effets modulaires.
# Chaque effet est une classe indépendante : apply(frame, t) -> frame.
# Tous les paramètres sont calibrés sur la vidéo référence.
#
# Hiérarchie :
#   EffectBase          (abstract)
#   ├── EffectContinuousZoom   → zoom global continu (1.00→1.04 sur toute la durée)
#   ├── EffectSpringOvershoot  → apparition spring (entrées texte/card)
#   ├── EffectWiggle           → tremblement organique (mots-clés)
#   ├── EffectHardCut          → sortie instantanée (EXIT de la référence)
#   └── EffectGradientText     → gradient horizontal sur texte accent

from __future__ import annotations
import math
from typing import Tuple, Optional
import numpy as np
from PIL import Image, ImageFilter

from .easing  import EasingLibrary
from .physics import SpringPhysics


class EffectBase:
    """Classe de base abstraite pour tous les effets V22."""
    def apply(self, frame: np.ndarray, t: float, **kwargs) -> np.ndarray:
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════════════════════
# EFFET 1 : EffectContinuousZoom
# REVERSE ENGINEERING : Zoom global 1.00→1.04 sur toute la durée, ease_in_out_sine.
# Subtil frame-à-frame, visible sur 5s+ → sensation "vivante" du plan.
# ══════════════════════════════════════════════════════════════════════════════

class EffectContinuousZoom(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 : Zoom progressif continu.

    Référence : scale_start=1.00, scale_end=1.03, easing='sine'.
    Le zoom est centré (crops les bords équitablement).
    Invisible sur <2s, imperceptible mais présent sur toute la durée.
    """

    def __init__(
        self,
        duration:    float,
        scale_start: float = 1.00,
        scale_end:   float = 1.03,
        easing:      str   = "sine",
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
        p     = min(max(t / self.duration, 0.0), 1.0)
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


# ══════════════════════════════════════════════════════════════════════════════
# EFFET 2 : EffectSpringOvershoot
# REVERSE ENGINEERING :
#   - Y offset initial = 8px (mesuré : text descend légèrement à l'entrée)
#   - Scale : 0 → 102% → 100% (overshoot 2% avec preset SNAP)
#   - Opacité : 0 → 1 en 60ms (3 frames à 30fps)
#   - Preset SpringPhysics.snap() : stiffness=900, damping=30
# ══════════════════════════════════════════════════════════════════════════════

class EffectSpringOvershoot(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 : Apparition Spring (entrées texte et cards).

    state_at(t_elapsed) → dict{scale, alpha, y_offset}
    apply(frame, t)     → frame mis à l'échelle

    slide_px=8 : offset Y mesuré pixel-exact dans la référence.
    """

    def __init__(
        self,
        spring:   Optional[SpringPhysics] = None,
        slide_px: int = 8,
    ):
        self.spring   = spring or SpringPhysics.snap()
        self.slide_px = slide_px

    def state_at(self, t_elapsed: float) -> dict:
        """Retourne {scale, alpha, y_offset} à t_elapsed secondes."""
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


# ══════════════════════════════════════════════════════════════════════════════
# EFFET 3 : EffectHardCut
# REVERSE ENGINEERING : Exit du texte = HARD CUT (0 frames de fondu).
# Le mot précédent disparaît à l'INSTANT EXACT où le suivant apparaît.
# ══════════════════════════════════════════════════════════════════════════════

class EffectHardCut(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 : Sortie instantanée.

    Contrairement à un fondu, le texte disparaît en 0 frames.
    C'est intentionnel dans la référence — rythme télévisuel/drum-machine.
    Utilisé pour TOUTES les sorties de mots dans la vidéo analysée.
    """

    def __init__(self, t_cut: float):
        self.t_cut = t_cut

    def apply(self, frame: np.ndarray, t: float, **_) -> np.ndarray:
        # Ce n'est pas un effet frame-level — la logique est dans le TimelineObject.
        # Cette classe sert de marqueur sémantique pour le TimelineEngine.
        return frame

    def is_alive(self, t: float) -> bool:
        return t < self.t_cut


# ══════════════════════════════════════════════════════════════════════════════
# EFFET 4 : EffectWiggle
# REVERSE ENGINEERING : Mots-clés (ACCENT/ACTION) — tremblement 5px, 200ms.
# Oscillation déterministe (sin/cos) avec enveloppe décroissante.
# ══════════════════════════════════════════════════════════════════════════════

class EffectWiggle(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 : Tremblement organique déterministe.

    Paramètres référence :
    • amplitude = 5px
    • decay     = 5.0 (atténuation ≈ 200ms)
    • fréquence = 8Hz
    • active    = 200ms post-apparition, puis s'arrête
    """

    def __init__(
        self,
        frequency: float = 8.0,
        amplitude: float = 5.0,
        decay:     float = 5.0,
        active_ms: float = 200.0,
    ):
        self.freq     = frequency
        self.amp      = amplitude
        self.decay    = decay
        self.active_s = active_ms / 1000.0

    def offset(self, t_elapsed: float) -> Tuple[int, int]:
        """Retourne (dx, dy) — déterministe, pas de random."""
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
        h, w   = frame.shape[:2]
        result = np.zeros_like(frame)
        src    = np.roll(np.roll(frame, dy, axis=0), dx, axis=1)
        result[:h, :w] = src[:h, :w]
        return result


# ══════════════════════════════════════════════════════════════════════════════
# EFFET 5 : EffectSlideExit
# REVERSE ENGINEERING : Exit slide-up avec ease_in_expo.
# Utilisé uniquement sur certains mots-clés ACCENT pour l'impact.
# Vitesse : SLIDE_OUT_PX=500 sur EXIT_DUR=0.14s → très rapide.
# ══════════════════════════════════════════════════════════════════════════════

class EffectSlideExit(EffectBase):
    """
    ARCHITECTURE_MASTER_V22 : Sortie par glissement vers le haut.

    t_exit_start : instant de début du slide
    t_full_end   : instant de fin (frame invisible)
    slide_px     : amplitude du glissement (500px par défaut)
    """

    def __init__(
        self,
        t_exit_start: float,
        t_full_end:   float,
        slide_px:     int   = 500,
    ):
        self.t_exit_start = t_exit_start
        self.t_full_end   = t_full_end
        self.slide_px     = slide_px

    def get_state(self, t: float) -> Tuple[int, float]:
        """Retourne (y_slide_offset, alpha_multiplier)."""
        if t < self.t_exit_start:
            return 0, 1.0
        exit_dur = max(self.t_full_end - self.t_exit_start, 1e-6)
        p        = min((t - self.t_exit_start) / exit_dur, 1.0)
        ease     = EasingLibrary.ease_in_expo(p)
        y_off    = -int(self.slide_px * ease)
        alpha    = max(0.0, 1.0 - ease ** 2)
        return y_off, alpha

    def apply(self, frame: np.ndarray, t: float, **_) -> np.ndarray:
        # Le slide est géré par le compositor (position_fn), pas frame-level.
        return frame