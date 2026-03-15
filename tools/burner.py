# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: SubtitleBurner — Moteur principal de rendu.
#
# DESCRIPTION :
#   Prend une timeline [(t_start, t_end, word), ...] et un clip vidéo.
#   Retourne un clip avec les mots brûlés pixel-perfect selon les règles
#   de la vidéo référence.
#
# PARADIGMES RÉFÉRENCE (reverse-engineered) :
#   1. UN MOT PAR FRAME — pas de groupes multi-mots
#   2. Centre Y = H × 0.499 (légèrement au-dessus du milieu)
#   3. Entrée spring : stiffness=900, damping=30 → settle ≈ 80ms
#   4. Exit HARD CUT : aucun fondu, disparition à t_end exact
#   5. Stop words : gris 160,160,160 + poids regular
#   6. Mots normaux : quasi-noir 17,17,17 + poids semibold
#   7. Mots ACCENT : gradient violet→mauve + poids bold
#   8. Zoom global continu : 1.00→1.03 sur toute la durée
#   9. Inversion noir/blanc : intervalles aléatoires (10-14 mots)

from __future__ import annotations

import re
import warnings
from typing import List, Optional, Tuple

import numpy as np

from .config import (
    TEXT_RGB, TEXT_RGB_INV, ACCENT_RGB, MUTED_RGB,
    TEXT_DIM_RGB, TEXT_DIM_INV, ACCENT_RGB_INV, MUTED_RGB_INV,
    ACCENT_GRADIENT_LEFT, ACCENT_GRADIENT_RIGHT,
    STOP_WORDS, KEYWORDS_ACCENT, KEYWORDS_MUTED,
    TEXT_ANCHOR_Y_RATIO, SPRING_STIFFNESS, SPRING_DAMPING,
    SPRING_SLIDE_PX, GLOBAL_ZOOM_START, GLOBAL_ZOOM_END,
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
)

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
    print("⚠️  moviepy manquant")


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE PRINCIPALE : SubtitleBurner
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleBurner:
    """
    ARCHITECTURE_MASTER_V22 : Moteur de sous-titres cinétiques.

    Replication exacte de la vidéo référence :
    ───────────────────────────────────────────
    • 1 mot par frame, centré sur TEXT_ANCHOR_Y_RATIO = 0.499
    • Entrée spring ultra-rapide (80ms) avec 2% overshoot
    • Exit hard cut (0 frame)
    • Stop words grisés, ACCENT en gradient violet, MUTED en rouge
    • Zoom global continu 1.00→1.03
    • Inversions noir/blanc toutes les 10-14 mots

    Usage minimal :
        burner = SubtitleBurner()
        out    = burner.burn_subtitles(clip, timeline)
    """

    # ── Dimensions canvas ──────────────────────────────────────────────────
    VID_W  = 1080
    VID_H  = 1920

    # ── Zone safe (texte) ──────────────────────────────────────────────────
    SAFE_W = 960     # Largeur max du texte
    SAFE_H = 200     # Marge haute/basse

    # ── Taille de police de base ──────────────────────────────────────────
    # ARCHITECTURE_MASTER_V22 : 80px est le point de départ.
    # Le moteur réduit automatiquement si le texte dépasse SAFE_W.
    FS_BASE  = 80
    FS_MIN   = 40

    # ── Paramètres inversion ──────────────────────────────────────────────
    INVERSION_WORD_MIN = 10
    INVERSION_WORD_MAX = 14

    def __init__(
        self,
        model_size:   str = "base",
        platform:     str = "shorts",
        fontsize:     int = None,
        spring_stiffness: int = SPRING_STIFFNESS,
        spring_damping:   int = SPRING_DAMPING,
    ):
        self.available        = WHISPER_AVAILABLE
        self.model            = None
        self.model_size       = model_size
        self.platform         = platform
        self.fontsize         = fontsize or self.FS_BASE

        # ARCHITECTURE_MASTER_V22 : Spring calibré sur la référence
        self._spring_factory = lambda: SpringPhysics(
            stiffness=spring_stiffness,
            damping=spring_damping,
        )

        # Centre Y mesuré dans la référence
        self._text_cy = int(self.VID_H * TEXT_ANCHOR_Y_RATIO)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — Classification & Style
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _strip_tags(text: str) -> str:
        return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

    def _classify(self, text: str) -> str:
        return classify_word(self._strip_tags(text))

    def _get_inv_color(self, color: tuple) -> tuple:
        """Retourne la couleur correspondante en thème inversé."""
        mapping = {
            TEXT_RGB:    TEXT_RGB_INV,
            TEXT_DIM_RGB: TEXT_DIM_INV,
            ACCENT_RGB:  ACCENT_RGB_INV,
            MUTED_RGB:   MUTED_RGB_INV,
        }
        return mapping.get(color, TEXT_RGB_INV)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2 — Construction d'un WordClip
    # ══════════════════════════════════════════════════════════════════════

    def _build_word_clip(
        self,
        word:    str,
        t_start: float,
        t_end:   float,
    ) -> Optional[WordClip]:
        """
        ARCHITECTURE_MASTER_V22 : Construit un WordClip depuis un mot.

        Étapes :
            1. Classifier le mot (STOP/NORMAL/ACCENT/MUTED/BADGE)
            2. Déterminer (fontsize, weight, color, use_gradient)
            3. Rendre arr (normal) et arr_inv (inversé)
            4. Calculer la position centrée
            5. Instancier WordClip avec spring individuel
        """
        clean = self._strip_tags(word).strip()
        if not clean or classify_word(clean) == WordClass.PAUSE:
            return None

        wclass = self._classify(clean)
        if wclass == WordClass.PAUSE:
            return None

        # ── Style ──────────────────────────────────────────────────────
        fs, weight, color, use_grad = get_word_style(wclass, self.fontsize)

        # ── Rendu normal ───────────────────────────────────────────────
        if use_grad:
            arr_n = render_text_gradient(
                clean, fs, weight=weight,
                color_left=ACCENT_GRADIENT_LEFT,
                color_right=ACCENT_GRADIENT_RIGHT,
                max_w=self.SAFE_W,
            )
            # Inversé : même gradient mais adapté (on garde le gradient)
            arr_i = render_text_gradient(
                clean, fs, weight=weight,
                color_left=(255 - ACCENT_GRADIENT_LEFT[0], 255 - ACCENT_GRADIENT_LEFT[1], 255 - ACCENT_GRADIENT_LEFT[2]),
                color_right=(255 - ACCENT_GRADIENT_RIGHT[0], 255 - ACCENT_GRADIENT_RIGHT[1], 255 - ACCENT_GRADIENT_RIGHT[2]),
                max_w=self.SAFE_W,
            )
        else:
            arr_n = render_text_solid(clean, fs, weight=weight, color=color,
                                      max_w=self.SAFE_W, inverted=False)
            arr_i = render_text_solid(clean, fs, weight=weight,
                                      color=self._get_inv_color(color),
                                      max_w=self.SAFE_W, inverted=True)

        # ── Position centrée ───────────────────────────────────────────
        # ARCHITECTURE_MASTER_V22 : Centrage pixel-exact sur TEXT_ANCHOR_Y_RATIO
        ph, pw = arr_n.shape[:2]
        x_pos  = (self.VID_W - pw) // 2
        y_pos  = self._text_cy - ph // 2

        # ── Clip ───────────────────────────────────────────────────────
        return WordClip(
            arr        = arr_n,
            arr_inv    = arr_i,
            target_x   = x_pos,
            target_y   = y_pos,
            t_start    = t_start,
            t_end      = t_end,          # HARD CUT : t_end exact
            is_keyword = wclass in (WordClass.ACCENT, WordClass.BADGE, WordClass.MUTED),
            spring     = self._spring_factory(),
        )

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3 — Calcul des intervalles d'inversion
    # ══════════════════════════════════════════════════════════════════════

    def _compute_inversion_intervals(
        self, clips: List[WordClip]
    ) -> List[Tuple[float, float]]:
        """
        ARCHITECTURE_MASTER_V22 : Inversions noir/blanc toutes les 10-14 mots.
        Décision déterministe basée sur le comptage de mots.
        """
        import random
        intervals    = []
        sorted_clips = sorted(clips, key=lambda c: c.t_start)
        inv_active   = False
        inv_start    = 0.0
        count        = 0
        threshold    = random.randint(self.INVERSION_WORD_MIN, self.INVERSION_WORD_MAX)

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
                threshold = random.randint(self.INVERSION_WORD_MIN, self.INVERSION_WORD_MAX)

        if inv_active and sorted_clips:
            intervals.append((inv_start, sorted_clips[-1].t_end))

        return intervals

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Burn Principal
    # ══════════════════════════════════════════════════════════════════════

    def burn_subtitles(
        self,
        video_clip,
        timeline: List[Tuple[float, float, str]],
    ):
        """
        ARCHITECTURE_MASTER_V22 : Point d'entrée principal.

        Input  : clip moviepy + timeline [(t_start, t_end, word), ...]
        Output : clip moviepy avec mots brûlés

        Pipeline :
            1. split_to_single_words  → 1 mot par entrée
            2. _build_word_clip       → rendu + position pour chaque mot
            3. _compute_inversion_intervals
            4. make_frame(t)          → composition + spring + zoom
        """
        if not MOVIEPY_AVAILABLE:
            return video_clip
        if not timeline:
            print("⚠️  [V22] Timeline vide.")
            return video_clip

        # ── Étape 1 : 1 mot par entrée ────────────────────────────────
        words = split_to_single_words(timeline)
        print(f"🎬 V22 Word Engine — {len(timeline)} entrées → {len(words)} mots individuels")

        # ── Étape 2 : Construction des WordClips ──────────────────────
        all_clips: List[WordClip] = []
        for t_start, t_end, word in words:
            clip = self._build_word_clip(word, t_start, t_end)
            if clip is not None:
                all_clips.append(clip)

        print(f"✅ V22 — {len(all_clips)} WordClips construits")

        # ── Étape 3 : Intervalles d'inversion ─────────────────────────
        inv_intervals = self._compute_inversion_intervals(all_clips)
        print(f"🎨 V22 — {len(inv_intervals)} intervalle(s) d'inversion")

        # ── Étape 4 : make_frame ──────────────────────────────────────
        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        # Mise à l'échelle si les dimensions diffèrent (ex: 576→1080)
        scale_x = vid_w / self.VID_W
        scale_y = vid_h / self.VID_H
        if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
            self._rescale_clips(all_clips, scale_x, scale_y)

        last_valid_frame = None

        def make_frame(t: float) -> np.ndarray:
            nonlocal last_valid_frame
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

            # Composition mots
            composite = compose_frame(t, all_clips, vid_w, vid_h,
                                      base_frame=base, inverted=is_inv)

            # Zoom global continu (1.00→1.03)
            p          = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = GLOBAL_ZOOM_START + (GLOBAL_ZOOM_END - GLOBAL_ZOOM_START) * p
            composite  = apply_continuous_zoom(composite, zoom_scale)

            return composite

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)
        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    def _rescale_clips(
        self,
        clips: List[WordClip],
        scale_x: float,
        scale_y: float,
    ) -> None:
        """
        ARCHITECTURE_MASTER_V22 : Mise à l'échelle des positions si le canvas
        est différent de 1080×1920 (ex: test à 576×1024).
        Modifie les clips in-place.
        """
        for c in clips:
            c.target_x = int(c.target_x * scale_x)
            c.target_y = int(c.target_y * scale_y)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — Rétrocompatibilité nexus_brain.py
    # ══════════════════════════════════════════════════════════════════════

    # Map sémantique → type SFX (appelé par nexus_brain._step_4_assembly)
    _SFX_MAP = {
        WordClass.BADGE:  "click_deep",
        WordClass.ACCENT: "click",
        WordClass.MUTED:  "swoosh",
        WordClass.NORMAL: "click",
        WordClass.STOP:   None,
        WordClass.PAUSE:  None,
    }

    def get_sfx_type(self, text: str) -> Optional[str]:
        """
        ARCHITECTURE_MASTER_V22 : Retourne le type SFX pour un texte de scène.
        Appelé par nexus_brain._step_4_assembly() pour le Sound Design.
        Rétrocompatible avec l'ancien SubtitleBurner.

        Retourne : "click_deep" | "click" | "swoosh" | None
        """
        clean = self._strip_tags(text).strip()
        if not clean or "[PAUSE]" in text.upper():
            return None
        wclass = self._classify(clean.split()[0] if clean.split() else clean)
        return self._SFX_MAP.get(wclass, "click")

    def _load_model(self):
        if not self.model and self.available:
            print(f"⏳  Chargement Whisper '{self.model_size}'…")
            self.model = whisper.load_model(self.model_size)

    def transcribe_to_timeline(
        self,
        audio_path: str,
        language:   str = None,
    ) -> List[Tuple[float, float, str]]:
        """
        ARCHITECTURE_MASTER_V22 : Transcription Whisper → timeline mot-par-mot.

        Retourne une liste de (t_start, t_end, word) avec timestamps WORD-LEVEL.
        Si word_timestamps n'est pas disponible, fallback sur segments.
        """
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
                t_e   = float(w.get("end", seg["end"]))
                if word:
                    all_words.append((t_s, t_e, word))

        # Fallback : pas de word_timestamps → utiliser les segments entiers
        if not all_words:
            for seg in result.get("segments", []):
                text = seg.get("text", "").strip()
                t_s  = float(seg["start"])
                t_e  = float(seg["end"])
                if text:
                    all_words.append((t_s, t_e, text))

        print(f"🎤 Whisper : {len(all_words)} mots transcrits")
        return all_words

    def generate_ass_file(self, audio_path, output_ass) -> bool:
        """Héritage V9 : génère un fichier .ass pour ffmpeg. Conservé pour compat."""
        timeline = self.transcribe_to_timeline(str(audio_path))
        if not timeline:
            return False

        header = """[Script Info]
Title: Nexus V22
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter-SemiBold,80,&H00111111&,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,3,0,1,0,1,5,0,0,420,1

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