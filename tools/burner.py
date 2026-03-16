# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V30: SubtitleBurner — Pipeline Complet Définitif (V30 Recalibration).
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V29 vs V25                                                           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  CORRECTION #1 — BROLL_CARD_CENTER_Y_RATIO : 0.614 → 0.471               ║
# ║    Mesuré: contenu image center = 482/1024 = 0.4707H                      ║
# ║    (V25 mesurait le centre du shadow bbox, pas de l'image)                 ║
# ║                                                                              ║
# ║  CORRECTION #2 — INVERSION_TIMESTAMPS                                     ║
# ║    V25: [(12.00, 12.79)] → V29: [(12.07, 12.77)]                          ║
# ║    Mesure frame-exact: cut entrant frame 362 (t=12.07s)                    ║
# ║                        cut sortant frame 383 (t=12.77s)                    ║
# ║                                                                              ║
# ║  CORRECTION #3 — TEXT_ANCHOR_Y_RATIO : 0.4970 → 0.4951                   ║
# ║    Dense scan 38 frames: mean=507/1024=0.4951H                            ║
# ║                                                                              ║
# ║  NOUVEAU V29 — CTA_CARD                                                   ║
# ║    Fenêtre t=40.20→44.10s (INVERSION_TIMESTAMPS[1]):                      ║
# ║    - Fond navy (14,14,26)                                                   ║
# ║    - Logo TikTok vectoriel centré à 0.461H                                 ║
# ║    - Search pill "@handle" centré à 0.571H                                 ║
# ║    - AUCUN sous-titre sur cette fenêtre                                     ║
# ║    - Spring entry depuis Y+40px au démarrage                               ║
# ║                                                                              ║
# ║  CONSERVÉ V25 :                                                             ║
# ║    TEXT_ANCHOR_Y FIXE (BROLL_TEXT_STAYS_PUT=True) ✓                       ║
# ║    Hard cut exit (t >= t_end strict) ✓                                      ║
# ║    SpringPhysics k=900 c=30 ✓                                              ║
# ║    Zoom global 1.00→1.03 ease_in_out_sine ✓                               ║
# ║    Sparkles inversion #1 (fond noir) ✓                                      ║
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
    BROLL_TEXT_STAYS_PUT,
    INVERSION_BG_COLOR_1, INVERSION_BG_COLOR_2,
    SPARKLE_ENABLED, SPARKLE_COUNT, SPARKLE_ORBIT_RX_RATIO,
    SPARKLE_ORBIT_RY_RATIO, SPARKLE_SPEED_BASE, SPARKLE_RADIUS_PX,
    SPARKLE_ALPHA, SPARKLE_ACTIVE_INVERSION,
    SPARKLE_COLOR_PRIMARY, SPARKLE_COLOR_SECONDARY, SPARKLE_COLOR_ACCENT,
    CTA_TIKTOK_HANDLE,
)
from .physics    import SpringPhysics, wiggle_offset
from .easing     import EasingLibrary
from .compositor import WordClip, compose_frame, apply_continuous_zoom
from .text_engine import (
    split_to_single_words, classify_word,
    get_word_style, WordClass,
)
from .graphics import (
    render_text_solid, render_text_gradient, find_font, measure_text,
    render_broll_card, render_cta_card,
)
from .timeline import TimelineObject, TimelineEngine

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
# ARCHITECTURE_MASTER_V29: SparkleEngine — VFX orbite mode sombre
# ══════════════════════════════════════════════════════════════════════════════

class SparkleEngine:
    """
    ARCHITECTURE_MASTER_V29: Moteur de particules (inversion #1 uniquement).

    Couleurs mesurées (precise_inv_0006.png numpy scan):
        rgb(55,0,98) → rgb(98,38,141) → rgb(83,23,126) → violet profond

    Physique orbite:
        x(t) = cx + rx * cos(phase + speed * t)
        y(t) = cy + ry * sin(phase + speed * t)
        alpha(t) = base * (1 + 0.3 * sin(speed * 3 * t))  ← pulsation
    """

    PALETTE = [
        SPARKLE_COLOR_PRIMARY,    # (40, 10, 90)
        SPARKLE_COLOR_SECONDARY,  # (90, 20, 160)
        SPARKLE_COLOR_ACCENT,     # (160, 40, 220)
        (30, 5, 70),
        (120, 30, 200),
    ]

    def __init__(self, vid_w: int, vid_h: int, n_particles: int = SPARKLE_COUNT):
        self.vid_w   = vid_w
        self.vid_h   = vid_h
        self.n       = n_particles
        self.orbit_rx = vid_w * SPARKLE_ORBIT_RX_RATIO
        self.orbit_ry = vid_h * SPARKLE_ORBIT_RY_RATIO

        base_phases  = [2.0 * math.pi * i / n_particles for i in range(n_particles)]
        self.phases  = [p + random.uniform(-0.3, 0.3) for p in base_phases]
        self.speeds  = [SPARKLE_SPEED_BASE + random.uniform(-0.4, 0.4) for _ in range(n_particles)]
        self.radii   = [SPARKLE_RADIUS_PX + random.randint(-2, 2) for _ in range(n_particles)]
        self.alphas  = [SPARKLE_ALPHA + random.uniform(-0.15, 0.15) for _ in range(n_particles)]
        self.colors  = [self.PALETTE[i % len(self.PALETTE)] for i in range(n_particles)]

    def render_onto(
        self,
        frame:    np.ndarray,
        t:        float,
        center_x: int,
        center_y: int,
    ) -> np.ndarray:
        from PIL import Image as PilImage, ImageDraw
        h, w = frame.shape[:2]
        img  = PilImage.fromarray(frame).convert("RGBA")
        over = PilImage.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(over)

        for i in range(self.n):
            angle = self.phases[i] + self.speeds[i] * t
            px    = int(center_x + self.orbit_rx * math.cos(angle))
            py    = int(center_y + self.orbit_ry * math.sin(angle))
            r     = self.radii[i]
            color = self.colors[i]

            pulse = 1.0 + 0.3 * math.sin(self.speeds[i] * 3.0 * t)
            alpha = int(self.alphas[i] * pulse * 255)
            alpha = max(0, min(255, alpha))

            for glow_r, glow_frac in [(r + 5, 0.15), (r + 3, 0.30), (r + 1, 0.60)]:
                ga = int(alpha * glow_frac)
                draw.ellipse([px-glow_r, py-glow_r, px+glow_r, py+glow_r], fill=(*color, ga))
            draw.ellipse([px-r, py-r, px+r, py+r], fill=(*color, alpha))

        result = PilImage.alpha_composite(img, over)
        return np.array(result.convert("RGB"))


# ══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE_MASTER_V29: SubtitleBurner Principal
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleBurner:
    """
    ARCHITECTURE_MASTER_V30: Moteur unifié sous-titres + B-Roll + Sparkles + CTA.

    Pipeline V29:
        1. split_to_single_words → 1 mot / entrée
        2. _build_word_clip (y_anchor = VID_H × 0.4951, FIXE)
        3. _build_broll_timelineobject → card à 0.471H (contenu, V29 corrigé)
        4. _build_cta_card → CTA TikTok pour fenêtre inv#2 (NOUVEAU V29)
        5. make_frame(t):
           a. Base frame
           b. Inversion BG avec couleur par fenêtre
           c. B-Roll cards via TimelineEngine (z=5)
           d. CTA card via TimelineEngine (z=15, remplace sous-titres)
           e. Texte via compose_frame (z=10, masqué pendant CTA)
           f. Sparkles (inversion #1 uniquement)
           g. Zoom global 1.00→1.03 ease_in_out_sine
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
        tiktok_handle:    str = None,
    ):
        self.available      = WHISPER_AVAILABLE
        self.model          = None
        self.model_size     = model_size
        self.platform       = platform
        self.fontsize       = fontsize if fontsize is not None else FS_BASE
        self.tiktok_handle  = tiktok_handle or CTA_TIKTOK_HANDLE

        self._spring_factory = lambda: SpringPhysics(
            stiffness=spring_stiffness,
            damping=spring_damping,
        )

        # ARCHITECTURE_MASTER_V29: ancrage Y=0.4951H FIXE
        self._text_cy       = int(self.VID_H * TEXT_ANCHOR_Y_RATIO)
        self._sparkle_engine: Optional[SparkleEngine] = None

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — Helpers texte
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
    # SECTION 2 — WordClip
    # ══════════════════════════════════════════════════════════════════════

    def _build_word_clip(
        self,
        word:     str,
        t_start:  float,
        t_end:    float,
        y_anchor: int = None,
    ) -> Optional[WordClip]:
        clean = self._strip_tags(word).strip()
        if not clean:
            return None

        wclass = self._classify(clean)
        if wclass == WordClass.PAUSE:
            return None

        fs, weight, color, use_grad = get_word_style(wclass, self.fontsize)

        if use_grad:
            arr_n = render_text_gradient(clean, fs, weight=weight,
                                         color_left=ACCENT_GRADIENT_LEFT,
                                         color_right=ACCENT_GRADIENT_RIGHT,
                                         max_w=self.SAFE_W)
            arr_i = render_text_gradient(clean, fs, weight=weight,
                                         color_left=ACCENT_GRADIENT_LEFT_INV,
                                         color_right=ACCENT_GRADIENT_RIGHT_INV,
                                         max_w=self.SAFE_W)
        else:
            arr_n = render_text_solid(clean, fs, weight=weight, color=color,
                                      max_w=self.SAFE_W, inverted=False)
            arr_i = render_text_solid(clean, fs, weight=weight,
                                      color=self._get_inv_color(color),
                                      max_w=self.SAFE_W, inverted=True)

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
    # SECTION 3 — Inversion timestamps
    # ══════════════════════════════════════════════════════════════════════

    def _compute_inversion_intervals(
        self,
        clips:    List[WordClip],
        duration: float,
    ) -> List[Tuple[float, float]]:
        """
        ARCHITECTURE_MASTER_V29: INVERSION_TIMESTAMPS prioritaires.
        V29: [(12.07, 12.77), (40.20, 44.10)] — mesures frame-exact.
        """
        intervals = [
            (t0, min(t1, duration))
            for t0, t1 in INVERSION_TIMESTAMPS
            if t0 < duration
        ]
        if intervals:
            return intervals

        # Fallback word-count (si aucun timestamp défini)
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
    # SECTION 4 — Couleur BG inversion
    # ══════════════════════════════════════════════════════════════════════

    def _get_inversion_bg_color(self, t: float) -> Tuple[int, int, int]:
        """
        ARCHITECTURE_MASTER_V29:
            Fenêtre #1 (t=12.07-12.77s): rgb(0,0,0) noir pur + sparkles
            Fenêtre #2 (t=40.20-44.10s): rgb(14,14,26) navy + CTA card
        """
        if t >= INVERSION_TIMESTAMPS[1][0]:
            return INVERSION_BG_COLOR_2
        return INVERSION_BG_COLOR_1

    def _is_sparkle_inversion(self, t: float, inv_intervals: List[Tuple[float, float]]) -> bool:
        if not SPARKLE_ENABLED:
            return False
        active_idx = SPARKLE_ACTIVE_INVERSION
        if active_idx < len(inv_intervals):
            t0, t1 = inv_intervals[active_idx]
            return t0 <= t < t1
        return False

    def _is_cta_window(self, t: float) -> bool:
        """
        ARCHITECTURE_MASTER_V29: True si t est dans la fenêtre CTA (inv#2).
        Pendant cette fenêtre: fond navy + CTA card, PAS de sous-titres.
        """
        if len(INVERSION_TIMESTAMPS) < 2:
            return False
        t0, t1 = INVERSION_TIMESTAMPS[1]
        return t0 <= t < t1

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5 — B-Roll TimelineObject (V29: center 0.471H CORRIGÉ)
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
        ARCHITECTURE_MASTER_V29: B-Roll card à BROLL_CARD_CENTER_Y_RATIO=0.471.

        MESURE DÉFINITIVE V29:
            content rows=[402,562] @576p → center=482/1024 = 0.4707H
            card_arr inclut shadow_pad=40px → cy_pos = cy_base - ch//2
            Le centre de l'IMAGE dans card_arr est bien à cy_base ✓

        Layout résultant @1080×1920:
            cy_base = 1920 × 0.471 = 904px
            text_cy = 1920 × 0.495 = 950px ∈ [card_top≈754, card_bot≈1054] ✓
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
        cx_pos = (vid_w - cw) // 2

        # ARCHITECTURE_MASTER_V29: BROLL_CARD_CENTER_Y_RATIO = 0.471 (V29 CORRIGÉ)
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
            z_index     = 5,
            tag         = "broll_card",
        ))

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — CTA Card TimelineObject (V29 NOUVEAU)
    # ══════════════════════════════════════════════════════════════════════

    def _build_cta_timelineobject(
        self,
        t_start:    float,
        t_end:      float,
        engine:     TimelineEngine,
        vid_w:      int,
        vid_h:      int,
    ) -> None:
        """
        ARCHITECTURE_MASTER_V29: CTA TikTok card pour fenêtre navy (inv#2).

        Caractéristiques (cta_0030.png mesures):
            - Fond navy rempli sur tout le canvas (géré par _get_inversion_bg_color)
            - Logo TikTok vectoriel centré à 0.461H
            - Texte "TikTok" sous le logo
            - Search pill "@handle" à 0.571H, width=0.618W
            - Spring entry: slide depuis Y+40px, settle 200ms

        z_index=15: au-dessus de tout (texte z=10, broll z=5)
        Les sous-titres sont SUPPRIMÉS pendant cette fenêtre (voir burn_subtitles).
        """
        try:
            cta_arr = render_cta_card(
                canvas_w = vid_w,
                canvas_h = vid_h,
                handle   = self.tiktok_handle,
            )
        except Exception as e:
            print(f"⚠️  CTA card render failed: {e}")
            return

        # La CTA card est un canvas complet → pos (0,0) + spring Y depuis +40px
        sp = self._spring_factory()

        def pos_fn(t: float) -> Tuple[int, int]:
            elapsed = t - t_start
            if elapsed < 0:
                return (0, 40)
            alpha = sp.clamped(elapsed)
            y_off = int(40 * max(0.0, 1.0 - alpha))
            return (0, y_off)

        def alpha_fn(t: float) -> float:
            elapsed = t - t_start
            if elapsed < 0:
                return 0.0
            return sp.clamped(elapsed)

        arr = cta_arr
        engine.add(TimelineObject(
            t_start  = t_start,
            t_end    = t_end,
            render_fn= lambda t, _a=arr: _a,
            pos_fn   = pos_fn,
            alpha_fn = alpha_fn,
            z_index  = 15,
            tag      = "cta_card",
        ))

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7 — Burn principal (V29)
    # ══════════════════════════════════════════════════════════════════════

    def burn_subtitles(
        self,
        video_clip,
        timeline:       List[Tuple[float, float, str]],
        broll_schedule: List[Tuple[float, float, str]] = None,
        cta_start:      float = None,
    ):
        """
        ARCHITECTURE_MASTER_V30: Point d'entrée principal (V30 recalibration).

        Paramètres:
            video_clip    : clip MoviePy source (fond blanc)
            timeline      : [(t_start, t_end, text), ...]  — sortie Whisper
            broll_schedule: [(t_start, t_end, image_path), ...]
            cta_start     : override du début CTA (défaut: INVERSION_TIMESTAMPS[1][0])

        Pipeline frame:
            1. Base frame (fond blanc)
            2. Inversion BG (noir pour inv#1, navy pour inv#2/CTA)
            3. B-Roll cards (z=5)
            4. CTA card (z=15) — remplace TOUT pendant inv#2
            5. Texte (z=10) — MASQUÉ pendant CTA window
            6. Sparkles (inv#1 uniquement)
            7. Zoom global 1.00→1.03
        """
        if not MOVIEPY_AVAILABLE:
            print("⚠️  moviepy indisponible")
            return video_clip
        if not timeline:
            print("⚠️  [V29] Timeline vide")
            return video_clip

        broll_schedule = broll_schedule or []

        # ── Étape 1: 1 mot par entrée ─────────────────────────────────────
        words = split_to_single_words(timeline)
        print(f"🎬 V29 Pipeline: {len(timeline)} entrées → {len(words)} mots")

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        scale_x = vid_w / self.VID_W
        scale_y = vid_h / self.VID_H
        scaled  = abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01

        # ARCHITECTURE_MASTER_V29: ancrage Y fixe 0.4951H
        actual_text_cy = int(self._text_cy * scale_y)

        # ── Étape 2: TimelineEngine (B-Roll + CTA) ────────────────────────
        engine = TimelineEngine(width=vid_w, height=vid_h)

        # ── Étape 3: WordClips ────────────────────────────────────────────
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

        print(f"✅ V29: {len(all_word_clips)} WordClips @ Y={actual_text_cy}px ({TEXT_ANCHOR_Y_RATIO}H)")

        # ── Étape 4: B-Roll dans TimelineEngine (z=5) ────────────────────
        for t_bs, t_be, img_path in broll_schedule:
            self._build_broll_timelineobject(img_path, t_bs, t_be, engine, vid_w, vid_h)
            card_cy = int(vid_h * BROLL_CARD_CENTER_Y_RATIO)
            print(f"  📸 Card [{t_bs:.2f},{t_be:.2f}s] → content_center_y={card_cy}px ({BROLL_CARD_CENTER_Y_RATIO}H)")

        # ── Étape 5: CTA Card dans TimelineEngine (z=15) ─────────────────
        # ARCHITECTURE_MASTER_V29: CTA automatique sur fenêtre inv#2
        if len(INVERSION_TIMESTAMPS) >= 2:
            cta_t0, cta_t1 = INVERSION_TIMESTAMPS[1]
            if cta_start is not None:
                cta_t0 = cta_start
            if cta_t0 < duration:
                cta_t1_capped = min(cta_t1, duration)
                self._build_cta_timelineobject(cta_t0, cta_t1_capped, engine, vid_w, vid_h)
                print(f"  📱 CTA card [{cta_t0:.2f},{cta_t1_capped:.2f}s] navy BG + TikTok logo")

        # ── Étape 6: Intervalles d'inversion ─────────────────────────────
        inv_intervals = self._compute_inversion_intervals(all_word_clips, duration)
        if inv_intervals:
            print(f"🎨 V29: {len(inv_intervals)} inversion(s): "
                  f"{[(f'{t0:.2f}s', f'{t1:.2f}s') for t0,t1 in inv_intervals]}")

        # ── Étape 7: SparkleEngine ────────────────────────────────────────
        if SPARKLE_ENABLED and inv_intervals:
            self._sparkle_engine = SparkleEngine(
                vid_w       = vid_w,
                vid_h       = vid_h,
                n_particles = SPARKLE_COUNT,
            )
            print(f"  ✨ Sparkles ({SPARKLE_COUNT} particules, inv#1 uniquement)")

        # ── Étape 8: make_frame ───────────────────────────────────────────
        last_valid_frame = None

        def make_frame(t: float) -> np.ndarray:
            nonlocal last_valid_frame

            try:
                base = video_clip.get_frame(t)
                last_valid_frame = base
            except Exception:
                base = (last_valid_frame if last_valid_frame is not None
                        else np.full((vid_h, vid_w, 3), 255, dtype=np.uint8))

            is_inv = any(t0 <= t < t1 for t0, t1 in inv_intervals)

            if is_inv:
                bg_color = self._get_inversion_bg_color(t)
                base     = np.full_like(base, 0)
                base[:, :, 0] = bg_color[0]
                base[:, :, 1] = bg_color[1]
                base[:, :, 2] = bg_color[2]

            # ÉTAPE A — B-Roll + CTA cards
            frame = engine.render_frame(t, base)

            # ÉTAPE B — Texte (MASQUÉ pendant CTA window pour effet full-screen)
            if not self._is_cta_window(t):
                frame = compose_frame(
                    t, all_word_clips, vid_w, vid_h,
                    base_frame=frame, inverted=is_inv,
                )

            # ÉTAPE C — Sparkles (inversion #1 seulement)
            if (self._sparkle_engine is not None
                    and self._is_sparkle_inversion(t, inv_intervals)):
                frame = self._sparkle_engine.render_onto(
                    frame    = frame,
                    t        = t,
                    center_x = vid_w // 2,
                    center_y = actual_text_cy,
                )

            # ÉTAPE D — Zoom global 1.00→1.03
            p          = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = GLOBAL_ZOOM_START + (GLOBAL_ZOOM_END - GLOBAL_ZOOM_START) * p
            frame      = apply_continuous_zoom(frame, zoom_scale)

            return frame

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)
        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 8 — Whisper
    # ══════════════════════════════════════════════════════════════════════

    def _load_model(self):
        if not self.model and self.available:
            print(f"⏳ Chargement Whisper '{self.model_size}'…")
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

        print(f"🎤 Whisper V29: {len(all_words)} mots transcrits")
        return all_words

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 9 — SFX Mapping
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
        timeline = self.transcribe_to_timeline(str(audio_path))
        if not timeline:
            return False

        header = """[Script Info]
Title: Nexus V29
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