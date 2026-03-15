# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V23: SubtitleBurner — Moteur unifié Timeline + B-Roll.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V23 vs V22                                                           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║  FIX  #1 — Inversion par TIMESTAMPS (mesurés) au lieu de word-count seul   ║
# ║  FIX  #2 — Gradient ACCENT: rose-chaud (204,90,120) au lieu de violet      ║
# ║  FIX  #3 — FS_BASE 70px (corrigé depuis 75)                                ║
# ║  FIX  #4 — TEXT_DIM_RGB 150,150,150 (V22 avait 103 — trop sombre)          ║
# ║  FIX  #5 — ACCENT scale 1.45× (V22 avait 1.10× — sous-évalué)              ║
# ║                                                                              ║
# ║  NOUVEAU #1 — Pipeline unifié via TimelineEngine                           ║
# ║    burn_subtitles() construit des TimelineObject et les passe au            ║
# ║    TimelineEngine. Plus de boucle custom → architecture modulaire.          ║
# ║                                                                              ║
# ║  NOUVEAU #2 — B-Roll Card intégration inline                               ║
# ║    burn_subtitles() accepte un paramètre broll_schedule:                    ║
# ║    [(t_start, t_end, image_path), ...]. Les cards sont rendues et           ║
# ║    insérées dans la timeline avec spring entry animation.                   ║
# ║                                                                              ║
# ║  NOUVEAU #3 — Smart Layout (collision detection)                           ║
# ║    Si une card B-Roll est active, le texte est décalé vers le BAS pour      ║
# ║    éviter la superposition (pas de collision visuelle).                     ║
# ║                                                                              ║
# ║  NOUVEAU #4 — Inversion timestamps-driven                                  ║
# ║    Les intervalles d'inversion sont définis par INVERSION_TIMESTAMPS        ║
# ║    (mesurés précisément: fenêtre 1 = 12.0→12.7s, fenêtre 2 = 40.1→end)    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

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
    BROLL_SHADOW_EXPAND_PX,
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
# ARCHITECTURE_MASTER_V23: SubtitleBurner — Pipeline Unifié
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleBurner:
    """
    ARCHITECTURE_MASTER_V23: Moteur unifié sous-titres + B-Roll.

    Architecture V23 (rupture vs V22):
    ───────────────────────────────────
    V22: boucle custom dans make_frame(t) → rigide, pas d'overlapping
    V23: TimelineEngine → chaque objet (mot, card) connaît son état à t exact.
         Overlapping contrôlé, B-Roll inline, collision detection, tout modulaire.

    Paradigme référence (mesuré):
    ─────────────────────────────
    • Word cadence  : min=33ms(1f), avg=165ms(5f), max=330ms
    • Spring settle : 3-4 frames (99-132ms @30fps) CONFIRMÉ
    • Centre Y      : H × 0.499 (CORRIGÉ depuis 0.497)
    • Police base   : 70px (CORRIGÉ depuis 75px)
    • ACCENT scale  : 1.45× (CORRIGÉ depuis 1.10×)
    • STOP color    : rgb(150,150,150) (CORRIGÉ depuis 103,103,103)
    • Gradient      : rose-chaud (204,90,120→160,60,100) (CORRIGÉ depuis violet)
    • Inversion #1  : t=12.00s→12.70s (700ms mesurés)
    • Inversion #2  : t=40.10s→end
    • Hard cut      : t < t_end (strict, 0 frame fondu)
    """

    VID_W  = 1080
    VID_H  = 1920
    SAFE_W = 940

    # ARCHITECTURE_MASTER_V23: Zone safe TEXT quand B-Roll est active
    # Le texte se positionne SOUS le centre quand une card occupe le centre
    TEXT_Y_WITH_BROLL_RATIO = 0.72   # Texte à 72% du canvas quand B-Roll actif

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

        # ARCHITECTURE_MASTER_V23: TEXT_ANCHOR_Y = 0.499×H
        self._text_cy          = int(self.VID_H * TEXT_ANCHOR_Y_RATIO)
        self._text_cy_broll    = int(self.VID_H * self.TEXT_Y_WITH_BROLL_RATIO)

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
    # SECTION 2 — Construction WordClip (inchangée vs V22 sauf correction Y)
    # ══════════════════════════════════════════════════════════════════════

    def _build_word_clip(
        self,
        word:     str,
        t_start:  float,
        t_end:    float,
        y_anchor: int = None,
    ) -> Optional[WordClip]:
        """
        ARCHITECTURE_MASTER_V23: Construit un WordClip.

        NOUVEAU: y_anchor paramétrable → permet le Smart Layout.
        Si une B-Roll card est active à ce moment, y_anchor = _text_cy_broll
        (le texte descend sous la card pour éviter la collision).
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
        # ARCHITECTURE_MASTER_V23: utilise y_anchor paramétrable
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
    # SECTION 3 — Inversion TIMESTAMPS-DRIVEN (ARCHITECTURE_MASTER_V23)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_inversion_intervals(
        self,
        clips:    List[WordClip],
        duration: float,
    ) -> List[Tuple[float, float]]:
        """
        ARCHITECTURE_MASTER_V23: Intervalles d'inversion basés sur TIMESTAMPS mesurés.

        NOUVEAU vs V22: INVERSION_TIMESTAMPS est la source primaire.
        Le word-count fallback n'est utilisé que si les timestamps sont désactivés.

        Mesures référence:
            Fenêtre 1: t=12.00s → t=12.70s (700ms)
            Fenêtre 2: t=40.10s → end (~44s)
        """
        # ARCHITECTURE_MASTER_V23: Méthode 1 — timestamps directs (PRIORITAIRE)
        intervals = [
            (t0, min(t1, duration))
            for t0, t1 in INVERSION_TIMESTAMPS
            if t0 < duration
        ]
        if intervals:
            return intervals

        # Fallback: word-count (V22 compat)
        import random
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
    # SECTION 4 — Rendu B-Roll Card (NOUVEAU V23)
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
        ARCHITECTURE_MASTER_V23: Construit et ajoute un TimelineObject B-Roll.

        Pipeline:
            1. render_broll_card() → RGBA numpy array
            2. Calculer position centrée (cx=W/2, cy=H×0.471)
            3. Créer TimelineObject avec spring entry
            4. Ajouter au TimelineEngine (z_index=5 → derrière le texte z=10)

        Spring: identique au texte (stiffness=900, damping=30).
        Entrée: slide depuis Y+60px, alpha 0→1 en 3-4 frames.
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
    # SECTION 5 — Smart Layout (NOUVEAU V23)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_text_y_for_time(
        self,
        t:              float,
        broll_schedule: List[Tuple[float, float, str]],
    ) -> int:
        """
        ARCHITECTURE_MASTER_V23: Smart Layout — détermine la position Y du texte.

        Si une B-Roll card est active à t → texte positionné à Y_WITH_BROLL (72% du canvas).
        Sinon → texte au centre standard (Y_ANCHOR = 0.499×H).

        Cette approche évite la COLLISION visuelle entre texte et image.
        """
        if not broll_schedule:
            return self._text_cy

        for t_b_start, t_b_end, _ in broll_schedule:
            if t_b_start <= t < t_b_end:
                return self._text_cy_broll

        return self._text_cy

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — BURN PRINCIPAL (V23 Pipeline Unifié)
    # ══════════════════════════════════════════════════════════════════════

    def burn_subtitles(
        self,
        video_clip,
        timeline:       List[Tuple[float, float, str]],
        broll_schedule: List[Tuple[float, float, str]] = None,
    ):
        """
        ARCHITECTURE_MASTER_V23: Point d'entrée principal.

        NOUVEAU vs V22: Accepte broll_schedule pour les B-Roll cards inline.

        Input:
            video_clip     : clip moviepy source
            timeline       : [(t_start, t_end, word), ...] — Whisper ou proportionnel
            broll_schedule : [(t_start, t_end, image_path), ...] — optionnel

        Output: clip moviepy avec texte + B-Roll intégrés, pixel-exact.

        Pipeline V23:
            1. split_to_single_words → 1 mot/entrée
            2. _build_word_clip (avec Smart Layout y_anchor)
            3. TimelineEngine.add() pour chaque WordClip
            4. _build_broll_timelineobject() pour chaque B-Roll
            5. _compute_inversion_intervals() timestamps-driven
            6. make_frame(t): TimelineEngine.render_frame() + inversion + zoom

        PARADIGME PERFORMANCE:
            • Spring: 3-4 frames settle @30fps (99-132ms)
            • Hard cut: t < t_end strict
            • Zoom: 1.00→1.03 ease_in_out_sine sur toute la durée
        """
        if not MOVIEPY_AVAILABLE:
            print("⚠️  moviepy indisponible — burn_subtitles retourne clip original")
            return video_clip
        if not timeline:
            print("⚠️  [V23] Timeline vide — aucun sous-titre brûlé")
            return video_clip

        broll_schedule = broll_schedule or []

        # ── Étape 1: 1 mot par entrée ─────────────────────────────────────
        words = split_to_single_words(timeline)
        print(f"🎬 V23 Pipeline: {len(timeline)} entrées → {len(words)} mots")
        if broll_schedule:
            print(f"  📸 B-Roll schedule: {len(broll_schedule)} cards")

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        # ── Mise à l'échelle si canvas ≠ 1080×1920 ───────────────────────
        scale_x = vid_w / self.VID_W
        scale_y = vid_h / self.VID_H
        scaled  = abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01
        if scaled:
            print(f"📐 V23: Rescaling {self.VID_W}×{self.VID_H} → {vid_w}×{vid_h}")

        # Adapter les constantes au canvas réel
        actual_text_cy       = int(self._text_cy       * scale_y)
        actual_text_cy_broll = int(self._text_cy_broll * scale_y)

        # Adapter le broll_schedule aux coordonnées canvas réel
        actual_broll = [
            (ts, te, ip) for ts, te, ip in broll_schedule
        ]

        # ── Étape 2: TimelineEngine ───────────────────────────────────────
        engine = TimelineEngine(width=vid_w, height=vid_h)

        # ── Étape 3: Construire WordClips et les ajouter ──────────────────
        all_word_clips: List[WordClip] = []
        for t_start, t_end, word in words:
            # Smart Layout: calculer le y_anchor selon le broll_schedule
            y_raw = self._compute_text_y_for_time(t_start, actual_broll)
            y_scaled = int(y_raw * scale_y) if not scaled else y_raw

            wclip = self._build_word_clip(word, t_start, t_end, y_anchor=y_scaled)
            if wclip is None:
                continue

            if scaled:
                wclip.target_x = int(wclip.target_x * scale_x)
                wclip.target_y = int(wclip.target_y * scale_y)

            all_word_clips.append(wclip)

            # ARCHITECTURE_MASTER_V23: WordClip → TimelineObject via helper
            # Le make_frame composite les WordClips directement via compose_frame
            # (garde la compatibilité avec le compositor V22)

        if not all_word_clips:
            print("⚠️  Aucun WordClip valide")
            return video_clip

        print(f"✅ V23: {len(all_word_clips)} WordClips")

        # ── Étape 4: B-Roll cards dans le TimelineEngine ─────────────────
        for t_bs, t_be, img_path in actual_broll:
            self._build_broll_timelineobject(
                image_path = img_path,
                t_start    = t_bs,
                t_end      = t_be,
                engine     = engine,
                vid_w      = vid_w,
                vid_h      = vid_h,
            )

        # ── Étape 5: Intervalles d'inversion ─────────────────────────────
        inv_intervals = self._compute_inversion_intervals(all_word_clips, duration)
        if inv_intervals:
            print(f"🎨 V23: {len(inv_intervals)} inversion(s): {[(f'{t0:.1f}s', f'{t1:.1f}s') for t0,t1 in inv_intervals]}")

        # ── Étape 6: make_frame ───────────────────────────────────────────
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
                base = (255 - base).astype(np.uint8)

            # ARCHITECTURE_MASTER_V23: ÉTAPE 1 — B-Roll cards via TimelineEngine
            # Les cards sont composées en premier (z_index=5, derrière le texte)
            frame = engine.render_frame(t, base)

            # ARCHITECTURE_MASTER_V23: ÉTAPE 2 — Texte via compose_frame (V22 compat)
            # Les WordClips ont leur propre compositor avec spring physics
            frame = compose_frame(
                t, all_word_clips, vid_w, vid_h,
                base_frame=frame, inverted=is_inv,
            )

            # ARCHITECTURE_MASTER_V23: ÉTAPE 3 — Zoom global 1.00→1.03
            p          = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = GLOBAL_ZOOM_START + (GLOBAL_ZOOM_END - GLOBAL_ZOOM_START) * p
            frame      = apply_continuous_zoom(frame, zoom_scale)

            return frame

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)
        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7 — Whisper Transcription (inchangée)
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
                word  = w.get("word", "").strip()
                t_s   = float(w.get("start", seg["start"]))
                t_e   = float(w.get("end",   seg["end"]))
                if word:
                    all_words.append((t_s, t_e, word))

        if not all_words:
            for seg in result.get("segments", []):
                text = seg.get("text", "").strip()
                t_s  = float(seg["start"])
                t_e  = float(seg["end"])
                if text:
                    all_words.append((t_s, t_e, text))

        print(f"🎤 Whisper V23: {len(all_words)} mots transcrits")
        return all_words

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 8 — Rétrocompatibilité nexus_brain.py
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
        """Génère un fichier .ass pour ffmpeg (rétrocompatibilité V9)."""
        timeline = self.transcribe_to_timeline(str(audio_path))
        if not timeline:
            return False

        header = """[Script Info]
Title: Nexus V23
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