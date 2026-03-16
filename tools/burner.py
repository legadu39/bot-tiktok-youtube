# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V25: SubtitleBurner — Sparkles VFX + BROLL CORRECTION.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V25 vs V24                                                           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  CORRECTION #1 (CRITIQUE) — BROLL_CARD_CENTER_Y_RATIO                     ║
# ║    V24: 0.663 → MESURÉ: 0.471H                                             ║
# ║    La card est centrée HAUTE (0.471H), le texte (0.498H) est               ║
# ║    à l'INTÉRIEUR des bounds de la card, pas en dessous.                    ║
# ║    Effet visuel: mot flotte en caption sur l'image B-Roll.                  ║
# ║                                                                              ║
# ║  CORRECTION #2 — BROLL_CARD_WIDTH_RATIO: 0.524 → 0.533                   ║
# ║    Mesuré: max_w=307px@576p / 576px = 0.5330W                             ║
# ║                                                                              ║
# ║  NOUVEAU V25 — SPARKLES VFX                                                ║
# ║    Intégration de tools/vfx.py dans le pipeline burn_subtitles()           ║
# ║    Sparkles actifs UNIQUEMENT sur inversion #1 (fond noir, t=12-12.79s)   ║
# ║    Couleur mesurée: violet profond (40,10,90)                               ║
# ║    Les sparkles orbitent autour du centre du texte actif                   ║
# ║                                                                              ║
# ║  CONSERVÉ V24:                                                              ║
# ║    TEXT_ANCHOR_Y_RATIO = 0.4985 (texte FIXE, ne bouge pas avec B-Roll) ✓  ║
# ║    INVERSION_TIMESTAMPS = [(12.0,12.79),(40.2,44.1)] ✓                    ║
# ║    SpringPhysics stiffness=900, damping=30 ✓                               ║
# ║    Hard cut exit (t_end strict <) ✓                                         ║
# ║    Global zoom 1.00→1.03 ease_in_out_sine ✓                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import math
import random
import re
import warnings
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from .config import (
    TEXT_RGB, TEXT_RGB_INV, ACCENT_RGB, MUTED_RGB,
    TEXT_DIM_RGB, TEXT_DIM_INV, ACCENT_RGB_INV, MUTED_RGB_INV,
    ACCENT_GRADIENT_LEFT, ACCENT_GRADIENT_RIGHT,
    ACCENT_GRADIENT_LEFT_INV, ACCENT_GRADIENT_RIGHT_INV,
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED,
    TEXT_ANCHOR_Y_RATIO, SPRING_STIFFNESS, SPRING_DAMPING,
    SPRING_SLIDE_PX, GLOBAL_ZOOM_START, GLOBAL_ZOOM_END,
    FS_BASE, FS_MIN, INVERSION_WORD_MIN, INVERSION_WORD_MAX,
    INVERSION_TIMESTAMPS,
    BROLL_CARD_WIDTH_RATIO, BROLL_CARD_CENTER_Y_RATIO,
    BROLL_CARD_RADIUS_RATIO, BROLL_SHADOW_BLUR, BROLL_SHADOW_OPACITY,
    BROLL_SHADOW_EXPAND_PX, BROLL_TEXT_STAYS_PUT,
    INVERSION_BG_COLOR_1, INVERSION_BG_COLOR_2,
    # NOUVEAU V25: Sparkles
    SPARKLE_ENABLED, SPARKLE_COUNT, SPARKLE_ORBIT_RX_RATIO,
    SPARKLE_ORBIT_RY_RATIO, SPARKLE_SPEED_BASE, SPARKLE_RADIUS_PX,
    SPARKLE_ALPHA, SPARKLE_ACTIVE_INVERSION,
    SPARKLE_COLOR_PRIMARY, SPARKLE_COLOR_SECONDARY, SPARKLE_COLOR_ACCENT,
)
from .physics   import SpringPhysics, wiggle_offset
from .easing    import EasingLibrary
from .compositor import WordClip, compose_frame, apply_continuous_zoom
from .text_engine import (
    split_to_single_words, classify_word,
    get_word_style, WordClass,
)
from .graphics  import (
    render_text_solid, render_text_gradient, find_font, measure_text,
    render_broll_card,
)
from .timeline  import TimelineObject, TimelineEngine

warnings.filterwarnings("ignore")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from moviepy.editor import VideoClip as MpVideoClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("⚠️  moviepy manquant — burn_subtitles désactivé")


# ══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V25: SparkleEngine — VFX orbite en mode sombre
# ══════════════════════════════════════════════════════════════════════════════

class SparkleEngine:
    """
    ARCHITECTURE_MASTER_V25: Moteur de particules pour les inversions sombres.

    Reproduit exactement les sparkling pixels violets mesurés à t=12.0s:
        - Couleur: rgb(40,10,90) violet profond (compressé: ~57,22,114 en JPEG)
        - Orbit center: centré sur le texte actif
        - 5 particules en orbite elliptique avec phases décalées
        - Actif UNIQUEMENT sur SPARKLE_ACTIVE_INVERSION (inversion #1 = fond noir)

    Physique des orbites:
        x(t) = cx + rx * cos(phase + speed * t)
        y(t) = cy + ry * sin(phase + speed * t)
        alpha = base_alpha * (1 + 0.3 * sin(speed * 3 * t))  # pulsation
    """

    PALETTE = [
        SPARKLE_COLOR_PRIMARY,     # (40, 10, 90) violet profond
        SPARKLE_COLOR_SECONDARY,   # (90, 20, 160) violet clair
        SPARKLE_COLOR_ACCENT,      # (160, 40, 220) violet lumineux
        (30, 5, 70),               # violet très sombre
        (120, 30, 200),            # violet brillant
    ]

    def __init__(self, vid_w: int, vid_h: int, n_particles: int = SPARKLE_COUNT):
        self.vid_w = vid_w
        self.vid_h = vid_h
        self.n = n_particles

        # Orbit dimensions proportionnelles au canvas
        self.orbit_rx = vid_w * SPARKLE_ORBIT_RX_RATIO
        self.orbit_ry = vid_h * SPARKLE_ORBIT_RY_RATIO

        # Phases décalées uniformément + jitter
        base_phases = [2.0 * math.pi * i / n_particles for i in range(n_particles)]
        self.phases = [p + random.uniform(-0.3, 0.3) for p in base_phases]
        self.speeds = [SPARKLE_SPEED_BASE + random.uniform(-0.4, 0.4)
                       for _ in range(n_particles)]
        self.radii  = [SPARKLE_RADIUS_PX + random.randint(-2, 2)
                       for _ in range(n_particles)]
        self.alphas = [SPARKLE_ALPHA + random.uniform(-0.15, 0.15)
                       for _ in range(n_particles)]
        self.colors = [self.PALETTE[i % len(self.PALETTE)]
                       for i in range(n_particles)]

    def render_onto(
        self,
        frame: np.ndarray,
        t: float,
        center_x: int,
        center_y: int,
    ) -> np.ndarray:
        """
        ARCHITECTURE_MASTER_V25: Dessine les sparkles en orbite sur le frame.

        Utilise PIL pour le rendu des ellipses de glow + core.
        Chaque sparkle a:
          - Un glow externe (2×radius, 25% opacité)
          - Un core lumineux (radius, pleine opacité)
          - Une pulsation alpha : α(t) = base_alpha * (1 + 0.3*sin(speed*3*t))
        """
        from PIL import Image as PilImage, ImageDraw

        h, w = frame.shape[:2]
        img  = PilImage.fromarray(frame).convert("RGBA")
        over = PilImage.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(over)

        for i in range(self.n):
            angle  = self.phases[i] + self.speeds[i] * t
            px     = int(center_x + self.orbit_rx * math.cos(angle))
            py     = int(center_y + self.orbit_ry * math.sin(angle))
            r      = self.radii[i]
            color  = self.colors[i]

            # Pulsation alpha
            pulse  = 1.0 + 0.3 * math.sin(self.speeds[i] * 3.0 * t)
            alpha  = int(self.alphas[i] * pulse * 255)
            alpha  = max(0, min(255, alpha))

            # Glow externe (gradient radial simplifié: 3 niveaux)
            for glow_r, glow_frac in [(r + 5, 0.15), (r + 3, 0.30), (r + 1, 0.60)]:
                ga = int(alpha * glow_frac)
                draw.ellipse(
                    [px - glow_r, py - glow_r, px + glow_r, py + glow_r],
                    fill=(*color, ga)
                )

            # Core
            draw.ellipse(
                [px - r, py - r, px + r, py + r],
                fill=(*color, alpha)
            )

        result = PilImage.alpha_composite(img, over)
        return np.array(result.convert("RGB"))


# ══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V25: SubtitleBurner Principal
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleBurner:
    """
    ARCHITECTURE_MASTER_V25: Moteur unifié sous-titres + B-Roll + Sparkles.

    CORRECTIONS vs V24:
    ───────────────────
    V24 (INCORRECT): BROLL_CARD_CENTER_Y_RATIO = 0.663 (card "sous" le texte)
    V25 (CORRECT):   BROLL_CARD_CENTER_Y_RATIO = 0.471 (card EN HAUT, texte dedans)

    Layout référence (mesures 8 frames stables):
    ────────────────────────────────────────────
    • Texte centre    : 510.8px/1024 = 0.4985H (FIXE, avec et sans B-Roll)
    • Card centre     : 482.5px/1024 = 0.471H  (CORRIGÉ depuis 0.663!)
    • Card top        : 401px/1024   = 0.392H
    • Card bottom     : 564px/1024   = 0.551H
    • Texte DANS card : 510 ∈ [401,564] ✓ — texte flotte sur l'image

    Paradigme de composition:
    ─────────────────────────
    1. Base frame (fond blanc ou inversé avec couleur par fenêtre)
    2. B-Roll cards via TimelineEngine (z_index=5, center=0.471H)
    3. Texte via compose_frame (z_index=10, toujours visible au-dessus)
    4. Sparkles via SparkleEngine (actifs en inversion #1 uniquement)
    5. Zoom global 1.00→1.03 ease_in_out_sine
    """

    VID_W  = 1080
    VID_H  = 1920
    SAFE_W = 940

    def __init__(
        self,
        model_size:       str = "base",
        platform:         str = "shorts",
        fontsize:         int = None,
        spring_stiffness: int = SPRING_STIFFNESS,
        spring_damping:   int = SPRING_DAMPING,
    ):
        self.available    = WHISPER_AVAILABLE
        self.model        = None
        self.model_size   = model_size
        self.platform     = platform
        self.fontsize     = fontsize if fontsize is not None else FS_BASE

        self._spring_factory = lambda: SpringPhysics(
            stiffness=spring_stiffness,
            damping=spring_damping,
        )

        # ARCHITECTURE_MASTER_V25: ancrage Y UNIQUE, FIXE à 0.4985H
        self._text_cy = int(self.VID_H * TEXT_ANCHOR_Y_RATIO)
        # Alias rétrocompatibilité (texte ne bouge JAMAIS avec B-Roll)
        self._text_cy_broll = self._text_cy

        # ARCHITECTURE_MASTER_V25: SparkleEngine initialisé ici,
        # redimensionné dans burn_subtitles() si canvas ≠ VID_W×VID_H
        self._sparkle_engine: Optional[SparkleEngine] = None

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — Classification & Style
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _strip_tags(text: str) -> str:
        return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

    def _classify(self, text: str) -> str:
        return classify_word(self._strip_tags(text))

    def _get_inv_color(self, color: tuple) -> tuple:
        mapping = {
            TEXT_RGB:     TEXT_RGB_INV,
            TEXT_DIM_RGB: TEXT_DIM_INV,
            ACCENT_RGB:   ACCENT_RGB_INV,
            MUTED_RGB:    MUTED_RGB_INV,
        }
        return mapping.get(color, TEXT_RGB_INV)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2 — Construction WordClip
    # ══════════════════════════════════════════════════════════════════════

    def _build_word_clip(
        self,
        word:     str,
        t_start:  float,
        t_end:    float,
        y_anchor: int = None,
    ) -> Optional[WordClip]:
        """
        ARCHITECTURE_MASTER_V25: Construit un WordClip.
        y_anchor est TOUJOURS self._text_cy (= VID_H × 0.4985).
        Le texte ne se déplace jamais, même en présence de B-Roll.
        """
        clean = self._strip_tags(word).strip()
        if not clean:
            return None

        wclass = self._classify(clean)
        if wclass == WordClass.PAUSE:
            return None

        fs, weight, color, use_grad = get_word_style(wclass, self.fontsize)

        if use_grad:
            arr_n = render_text_gradient(
                clean, fs, weight=weight,
                color_left=ACCENT_GRADIENT_LEFT,
                color_right=ACCENT_GRADIENT_RIGHT,
                max_w=self.SAFE_W,
            )
            arr_i = render_text_gradient(
                clean, fs, weight=weight,
                color_left=ACCENT_GRADIENT_LEFT_INV,
                color_right=ACCENT_GRADIENT_RIGHT_INV,
                max_w=self.SAFE_W,
            )
        else:
            arr_n = render_text_solid(
                clean, fs, weight=weight, color=color,
                max_w=self.SAFE_W, inverted=False,
            )
            arr_i = render_text_solid(
                clean, fs, weight=weight,
                color=self._get_inv_color(color),
                max_w=self.SAFE_W, inverted=True,
            )

        ph, pw = arr_n.shape[:2]
        x_pos  = (self.VID_W - pw) // 2
        cy_use = y_anchor if y_anchor is not None else self._text_cy
        y_pos  = cy_use - ph // 2

        return WordClip(
            arr        = arr_n,
            arr_inv    = arr_i,
            target_x   = x_pos,
            target_y   = y_pos,
            t_start    = t_start,
            t_end      = t_end,
            is_keyword = wclass in (WordClass.ACCENT, WordClass.BADGE, WordClass.MUTED),
            spring     = self._spring_factory(),
        )

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3 — Inversion timestamps (V25 = V24 confirmé)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_inversion_intervals(
        self,
        clips:    List[WordClip],
        duration: float,
    ) -> List[Tuple[float, float]]:
        """
        ARCHITECTURE_MASTER_V25: Intervalles d'inversion.
        Priorité: INVERSION_TIMESTAMPS (mesurés frame-par-frame).
        Fallback: word-count (V22 compat).
        """
        intervals = [
            (t0, min(t1, duration))
            for t0, t1 in INVERSION_TIMESTAMPS
            if t0 < duration
        ]
        if intervals:
            return intervals

        # Fallback word-count
        intervals    = []
        sorted_clips = sorted(clips, key=lambda c: c.t_start)
        inv_active   = False
        inv_start    = 0.0
        count        = 0
        threshold    = random.randint(INVERSION_WORD_MIN, INVERSION_WORD_MAX)

        for clip in sorted_clips:
            count += 1
            if count >= threshold:
                if not inv_active:
                    inv_active = True
                    inv_start  = clip.t_start
                else:
                    inv_active = False
                    intervals.append((inv_start, clip.t_start))
                count     = 0
                threshold = random.randint(INVERSION_WORD_MIN, INVERSION_WORD_MAX)

        if inv_active and sorted_clips:
            intervals.append((inv_start, sorted_clips[-1].t_end))

        return intervals

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Couleur de fond inversion (V25 = V24 confirmé)
    # ══════════════════════════════════════════════════════════════════════

    def _get_inversion_bg_color(self, t: float) -> Tuple[int, int, int]:
        """
        ARCHITECTURE_MASTER_V25:
            Inversion #1 (t=12.0-12.79s) : rgb(0,0,0) noir pur + sparkles
            Inversion #2 (t=40.2-44.1s)  : rgb(14,14,26) navy profond + CTA B-Roll
        """
        if t >= 40.20:
            return INVERSION_BG_COLOR_2   # (14, 14, 26)
        return INVERSION_BG_COLOR_1       # (0, 0, 0)

    def _is_sparkle_inversion(self, t: float, inv_intervals: List[Tuple[float, float]]) -> bool:
        """
        ARCHITECTURE_MASTER_V25: True si t est dans l'inversion #1 (fond noir + sparkles).
        Sparkles UNIQUEMENT sur SPARKLE_ACTIVE_INVERSION (index 0 = inv#1).
        """
        if not SPARKLE_ENABLED:
            return False
        active_idx = SPARKLE_ACTIVE_INVERSION
        if active_idx < len(inv_intervals):
            t0, t1 = inv_intervals[active_idx]
            return t0 <= t < t1
        return False

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5 — B-Roll Card (V25: position CORRIGÉE 0.471H)
    # ══════════════════════════════════════════════════════════════════════

    def _build_broll_timelineobject(
        self,
        image_path: str,
        t_start:    float,
        t_end:      float,
        engine:     TimelineEngine,
        vid_w:      int,
        vid_h:      int,
    ) -> None:
        """
        ARCHITECTURE_MASTER_V25: Card B-Roll positionnée à 0.471H.

        CORRECTION MAJEURE vs V24:
            V24: cy_base = vid_h * 0.663  → card en BAS (INCORRECT)
            V25: cy_base = vid_h * 0.471  → card en HAUT-CENTRE (MESURÉ)

        Layout résultant (1080×1920):
            Card center Y = 1920 * 0.471 = 904px
            Card top      = 904 - card_h/2 ≈ 757px  (0.394H)
            Card bottom   = 904 + card_h/2 ≈ 1058px (0.551H)
            Texte centre  = 1920 * 0.4985 = 957px    (0.498H)

            → Texte à 957px est DANS la card [757,1058]
            → Le texte (z=10) apparaît AU-DESSUS de l'image (z=5)
            → Effet "caption flottant sur l'image" — ultra-premium ✓

        Pipeline spring entry:
            Slide depuis Y+8px, alpha 0→1 en ~200ms (6 frames@30fps)
        """
        try:
            card_arr = render_broll_card(
                image_path     = image_path,
                canvas_w       = vid_w,
                corner_radius  = None,
                shadow_blur    = BROLL_SHADOW_BLUR,
                shadow_opacity = BROLL_SHADOW_OPACITY,
            )
        except Exception as e:
            print(f"⚠️  B-Roll render failed: {e}")
            return

        ch, cw = card_arr.shape[:2]
        cx_pos  = (vid_w - cw) // 2

        # ARCHITECTURE_MASTER_V25: BROLL_CARD_CENTER_Y_RATIO = 0.471 (CORRIGÉ)
        # La card est centrée dans le tiers supérieur-milieu de l'écran
        cy_base = int(vid_h * BROLL_CARD_CENTER_Y_RATIO)
        cy_pos  = cy_base - ch // 2

        sp = self._spring_factory()
        engine.add(engine.make_spring_entry_object(
            image_array = card_arr,
            t_start     = t_start,
            t_end       = t_end,
            x           = cx_pos,
            y           = cy_pos,
            spring      = sp,
            slide_px    = SPRING_SLIDE_PX,
            z_index     = 5,    # Derrière le texte (z=10)
            tag         = "broll_card",
        ))

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — Ancrage texte (V25: TOUJOURS fixe, confirmé)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_text_y_for_time(
        self,
        t:              float,
        broll_schedule: List[Tuple[float, float, str]],
    ) -> int:
        """
        ARCHITECTURE_MASTER_V25: Retourne TOUJOURS self._text_cy.

        Mesuré sur 8 frames stables: 509.5, 511.5, 510.5, 514, 509,
        509.5, 511.5, 511.5 → moy=510.8 / 1024 = 0.4984H ≈ 0.4985H

        Confirmé avec ET sans B-Roll → BROLL_TEXT_STAYS_PUT = True permanent.
        """
        return self._text_cy  # Ancrage absolu, jamais modifié

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7 — BURN PRINCIPAL (V25)
    # ══════════════════════════════════════════════════════════════════════

    def burn_subtitles(
        self,
        video_clip,
        timeline:       List[Tuple[float, float, str]],
        broll_schedule: List[Tuple[float, float, str]] = None,
    ):
        """
        ARCHITECTURE_MASTER_V25: Point d'entrée principal.

        Pipeline V25 (corrections vs V24):
            1. split_to_single_words → 1 mot/entrée
            2. _build_word_clip (y_anchor = _text_cy = 0.4985H, FIXE)
            3. _build_broll_timelineobject → card à 0.471H (CORRIGÉ)
            4. make_frame(t):
               a. Base frame
               b. Inversion bg avec couleur par fenêtre
               c. B-Roll cards via TimelineEngine (z=5) → image derrière
               d. Texte via compose_frame (z=10) → mot devant l'image
               e. Sparkles via SparkleEngine (inversion #1 uniquement) ← NOUVEAU
               f. Zoom global 1.00→1.03
        """
        if not MOVIEPY_AVAILABLE:
            print("⚠️  moviepy indisponible — burn_subtitles retourne clip original")
            return video_clip
        if not timeline:
            print("⚠️  [V25] Timeline vide — aucun sous-titre brûlé")
            return video_clip

        broll_schedule = broll_schedule or []

        # ── Étape 1: 1 mot par entrée ─────────────────────────────────────
        words = split_to_single_words(timeline)
        print(f"🎬 V25 Pipeline: {len(timeline)} entrées → {len(words)} mots")
        if broll_schedule:
            print(f"  📸 B-Roll: {len(broll_schedule)} cards @ center={BROLL_CARD_CENTER_Y_RATIO}H")
            print(f"  📌 Texte FIXE @ {TEXT_ANCHOR_Y_RATIO}H (inside card bounds)")
        if SPARKLE_ENABLED:
            print(f"  ✨ Sparkles: ACTIFS sur inversion #{SPARKLE_ACTIVE_INVERSION+1}")

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        scale_x = vid_w / self.VID_W
        scale_y = vid_h / self.VID_H
        scaled  = abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01
        if scaled:
            print(f"📐 V25: Scale {self.VID_W}×{self.VID_H} → {vid_w}×{vid_h}")

        # ARCHITECTURE_MASTER_V25: ancrage Y fixe (0.4985H)
        actual_text_cy = int(self._text_cy * scale_y)

        # ── Étape 2: TimelineEngine pour B-Roll ───────────────────────────
        engine = TimelineEngine(width=vid_w, height=vid_h)

        # ── Étape 3: Construire WordClips ─────────────────────────────────
        all_word_clips: List[WordClip] = []
        for t_start, t_end, word in words:
            wclip = self._build_word_clip(word, t_start, t_end, y_anchor=actual_text_cy)
            if wclip is None:
                continue
            if scaled:
                wclip.target_x = int(wclip.target_x * scale_x)
                wclip.target_y = int(wclip.target_y * scale_y)
            all_word_clips.append(wclip)

        if not all_word_clips:
            print("⚠️  Aucun WordClip valide")
            return video_clip

        print(f"✅ V25: {len(all_word_clips)} WordClips @ ancrage Y={actual_text_cy}px ({TEXT_ANCHOR_Y_RATIO}H)")

        # ── Étape 4: B-Roll dans le TimelineEngine (z=5) ──────────────────
        for t_bs, t_be, img_path in broll_schedule:
            self._build_broll_timelineobject(
                image_path = img_path,
                t_start    = t_bs,
                t_end      = t_be,
                engine     = engine,
                vid_w      = vid_w,
                vid_h      = vid_h,
            )
            card_cy = int(vid_h * BROLL_CARD_CENTER_Y_RATIO)
            print(f"  📸 Card [{t_bs:.2f},{t_be:.2f}s] → center_y={card_cy}px ({BROLL_CARD_CENTER_Y_RATIO}H)")

        # ── Étape 5: Intervalles d'inversion ─────────────────────────────
        inv_intervals = self._compute_inversion_intervals(all_word_clips, duration)
        if inv_intervals:
            print(f"🎨 V25: {len(inv_intervals)} inversion(s): "
                  f"{[(f'{t0:.2f}s', f'{t1:.2f}s') for t0,t1 in inv_intervals]}")

        # ── Étape 6: Initialiser SparkleEngine ────────────────────────────
        if SPARKLE_ENABLED and inv_intervals:
            self._sparkle_engine = SparkleEngine(
                vid_w      = vid_w,
                vid_h      = vid_h,
                n_particles = SPARKLE_COUNT,
            )
            print(f"  ✨ SparkleEngine initialisé ({SPARKLE_COUNT} particules, "
                  f"orbit={self._sparkle_engine.orbit_rx:.0f}×{self._sparkle_engine.orbit_ry:.0f}px)")

        # ── Étape 7: make_frame ───────────────────────────────────────────
        last_valid_frame = None

        def make_frame(t: float) -> np.ndarray:
            nonlocal last_valid_frame

            # Frame source
            try:
                base = video_clip.get_frame(t)
                last_valid_frame = base
            except Exception:
                base = (last_valid_frame if last_valid_frame is not None
                        else np.full((vid_h, vid_w, 3), 255, dtype=np.uint8))

            # Détection inversion
            is_inv = any(t0 <= t < t1 for t0, t1 in inv_intervals)

            if is_inv:
                bg_color = self._get_inversion_bg_color(t)
                base     = np.full_like(base, 0)
                base[:, :, 0] = bg_color[0]
                base[:, :, 1] = bg_color[1]
                base[:, :, 2] = bg_color[2]

            # ÉTAPE A — B-Roll cards (z=5, DERRIÈRE le texte)
            # La card est à 0.471H, le texte à 0.498H → texte dans la card
            frame = engine.render_frame(t, base)

            # ÉTAPE B — Texte (z=10, AU-DESSUS de la card et de tout)
            frame = compose_frame(
                t, all_word_clips, vid_w, vid_h,
                base_frame=frame, inverted=is_inv,
            )

            # ÉTAPE C — Sparkles (UNIQUEMENT inversion #1, fond noir)
            # ARCHITECTURE_MASTER_V25: SparkleEngine orbit autour du texte actif
            if (self._sparkle_engine is not None
                    and self._is_sparkle_inversion(t, inv_intervals)):
                frame = self._sparkle_engine.render_onto(
                    frame    = frame,
                    t        = t,
                    center_x = vid_w // 2,
                    center_y = actual_text_cy,
                )

            # ÉTAPE D — Zoom global 1.00→1.03 ease_in_out_sine
            p          = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = GLOBAL_ZOOM_START + (GLOBAL_ZOOM_END - GLOBAL_ZOOM_START) * p
            frame      = apply_continuous_zoom(frame, zoom_scale)

            return frame

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)
        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 8 — Whisper Transcription
    # ══════════════════════════════════════════════════════════════════════

    def _load_model(self):
        if not self.model and self.available:
            print(f"⏳  Chargement Whisper '{self.model_size}'…")
            self.model = whisper.load_model(self.model_size)

    def transcribe_to_timeline(
        self,
        audio_path: str,
        language:   str = None,
    ) -> List[Tuple[float, float, str]]:
        if not self.available:
            print("⚠️  Whisper non disponible.")
            return []

        self._load_model()
        opts = {"word_timestamps": True}
        if language:
            opts["language"] = language

        result    = self.model.transcribe(str(audio_path), **opts)
        all_words = []

        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                word = w.get("word", "").strip()
                t_s  = float(w.get("start", seg["start"]))
                t_e  = float(w.get("end",   seg["end"]))
                if word:
                    all_words.append((t_s, t_e, word))

        if not all_words:
            for seg in result.get("segments", []):
                text = seg.get("text", "").strip()
                if text:
                    all_words.append((float(seg["start"]), float(seg["end"]), text))

        print(f"🎤 Whisper V25: {len(all_words)} mots transcrits")
        return all_words

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 9 — SFX Mapping & Rétrocompatibilité
    # ══════════════════════════════════════════════════════════════════════

    _SFX_MAP = {
        WordClass.BADGE:  "click_deep",
        WordClass.ACCENT: "click",
        WordClass.MUTED:  "swoosh",
        WordClass.NORMAL: "click",
        WordClass.STOP:   None,
        WordClass.PAUSE:  None,
    }

    def get_sfx_type(self, text: str) -> Optional[str]:
        clean = self._strip_tags(text).strip()
        if not clean or "[PAUSE]" in text.upper():
            return None
        first_word = clean.split()[0] if clean.split() else clean
        wclass     = self._classify(first_word)
        return self._SFX_MAP.get(wclass, "click")

    def generate_ass_file(self, audio_path: str, output_ass: str) -> bool:
        """Génère un fichier .ass pour ffmpeg (rétrocompatibilité)."""
        timeline = self.transcribe_to_timeline(str(audio_path))
        if not timeline:
            return False

        header = """[Script Info]
Title: Nexus V25
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter-SemiBold,70,&H00191919&,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,3,0,1,0,1,5,0,0,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""

        def to_ass(s: float) -> str:
            h  = int(s // 3600)
            m  = int((s % 3600) // 60)
            sc = int(s % 60)
            cs = int((s - int(s)) * 100)
            return f"{h}:{m:02d}:{sc:02d}.{cs:02d}"

        with open(str(output_ass), "w", encoding="utf-8") as f:
            f.write(header)
            for t_s, t_e, word in split_to_single_words(timeline):
                pop = r"{\fscx0\fscy0\alpha&HFF&\t(0,80,\fscx103\fscy103\alpha&H00&)\t(80,140,\fscx100\fscy100)}"
                f.write(f"Dialogue: 0,{to_ass(t_s)},{to_ass(t_e)},Default,,0,0,,{pop}{word}\n")

        return True