# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V24: SubtitleBurner — Correction architecturale majeure.
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V24 vs V23                                                           ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  CORRECTION ARCHITECTURALE CENTRALE (reverse-engineering frame-par-frame)  ║
# ║                                                                              ║
# ║  V23 (INCORRECT) :                                                          ║
# ║    TEXT_Y_WITH_BROLL_RATIO = 0.72 → texte se déplace vers le bas          ║
# ║    BROLL_CARD_CENTER_Y_RATIO = 0.4717 → card au centre écran              ║
# ║                                                                              ║
# ║  V24 (CORRECT, mesuré) :                                                   ║
# ║    Le texte reste TOUJOURS à 0.4985H — aucun déplacement                  ║
# ║    La card se positionne à 0.663H — EN BAS du texte                       ║
# ║    Layout: texte (0.4985H) + card sous le texte (0.663H)                  ║
# ║                                                                              ║
# ║  FIX #1 — _compute_text_y_for_time() retourne TOUJOURS self._text_cy      ║
# ║            La méthode existe pour extensibilité future mais ne déplace     ║
# ║            plus le texte. BROLL_TEXT_STAYS_PUT = True.                     ║
# ║                                                                              ║
# ║  FIX #2 — _build_broll_timelineobject() : card positionnée à 0.663H       ║
# ║            (BROLL_CARD_CENTER_Y_RATIO = 0.663 dans config V24)            ║
# ║                                                                              ║
# ║  FIX #3 — Couleurs bg inversion : bg1=noir pur, bg2=navy (14,14,26)       ║
# ║            make_frame() applique la couleur exacte mesurée                 ║
# ║                                                                              ║
# ║  FIX #4 — INVERSION_TIMESTAMPS : (12.00,12.79) et (40.20,44.10)          ║
# ║            (V23 avait (12.0,12.7) et (40.1,44.1))                         ║
# ║                                                                              ║
# ║  CONSERVÉ depuis V23 :                                                      ║
# ║    Pipeline unifié TimelineEngine ✓                                         ║
# ║    spring entry pour les cards (stiffness=900, damping=30) ✓              ║
# ║    Word-level Whisper timeline ✓                                            ║
# ║    Global zoom 1.00→1.03 ease_in_out_sine ✓                               ║
# ║    Hard cut (t < t_end strict) ✓                                            ║
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
    BROLL_SHADOW_EXPAND_PX, BROLL_TEXT_STAYS_PUT,
    INVERSION_BG_COLOR_1, INVERSION_BG_COLOR_2,
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
# ARCHITECTURE_MASTER_V24: SubtitleBurner — Layout Corrigé
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleBurner:
    """
    ARCHITECTURE_MASTER_V24: Moteur unifié sous-titres + B-Roll.

    CORRECTION CENTRALE vs V23:
    ───────────────────────────
    V23 (INCORRECT): Texte se déplaçait à 0.72H quand B-Roll actif.
    V24 (CORRECT):   Texte reste à 0.4985H EN PERMANENCE.
                     La B-Roll card se positionne à 0.663H (SOUS le texte).

    Layout référence mesuré (576×1024 @30fps):
    ────────────────────────────────────────────
    • Texte centre    : 510.5/1024 = 0.4985H (FIXE avec/sans B-Roll)
    • Card centre     : 679/1024 = 0.663H    (dans la moitié basse)
    • Card top        : ~497/1024 = 0.485H   (légère superposition avec texte)
    • Card bottom     : ~861/1024 = 0.841H
    • Inversion #1    : t=12.00→12.79s, bg=rgb(0,0,0) pur noir
    • Inversion #2    : t=40.20→44.10s, bg=rgb(14,14,26) navy

    Paradigme de composition :
    ─────────────────────────
    1. Base frame (fond blanc ou inversé)
    2. B-Roll cards via TimelineEngine (z_index=5)
    3. Texte via compose_frame (z_index=10, toujours au-dessus des cards)
    4. Zoom global 1.00→1.03 ease_in_out_sine
    """

    VID_W  = 1080
    VID_H  = 1920
    SAFE_W = 940

    # ARCHITECTURE_MASTER_V24: Suppression de TEXT_Y_WITH_BROLL_RATIO
    # Le texte ne bouge plus. Ce ratio est maintenu uniquement pour
    # rétrocompatibilité si besoin d'override via sous-classe.
    TEXT_Y_WITH_BROLL_RATIO = TEXT_ANCHOR_Y_RATIO  # = 0.4985 (INCHANGÉ!)

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

        # ARCHITECTURE_MASTER_V24: Un seul ancrage Y pour le texte (0.4985H)
        # TEXT_ANCHOR_Y_RATIO = 0.4985 (mesuré: 510.5/1024)
        self._text_cy = int(self.VID_H * TEXT_ANCHOR_Y_RATIO)

        # ARCHITECTURE_MASTER_V24: _text_cy_broll = _text_cy (texte ne bouge plus)
        # Alias pour rétrocompatibilité du code appelant
        self._text_cy_broll = self._text_cy

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
        ARCHITECTURE_MASTER_V24: Construit un WordClip.

        y_anchor est passé par burn_subtitles() mais sera toujours self._text_cy
        dans V24 (texte ne bouge plus). Paramètre conservé pour extensibilité.
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
    # SECTION 3 — Inversion TIMESTAMPS-DRIVEN (V24: timestamps corrigés)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_inversion_intervals(
        self,
        clips:    List[WordClip],
        duration: float,
    ) -> List[Tuple[float, float]]:
        """
        ARCHITECTURE_MASTER_V24: Intervalles d'inversion corrigés.

        Mesures frame-par-frame confirmées:
            Fenêtre 1: t=12.00s → 12.79s (790ms = 24 frames @30fps)
                       Détecté: dark bg entre idx=119 et idx=136
            Fenêtre 2: t=40.20s → 44.10s
                       Détecté: dark bg depuis t≈40.33s
        """
        # Méthode 1: timestamps primaires (PRIORITAIRE)
        intervals = [
            (t0, min(t1, duration))
            for t0, t1 in INVERSION_TIMESTAMPS
            if t0 < duration
        ]
        if intervals:
            return intervals

        # Fallback: word-count (V22/V23 compat)
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
    # SECTION 4 — Couleur de fond inversion (NOUVEAU V24)
    # ══════════════════════════════════════════════════════════════════════

    def _get_inversion_bg_color(self, t: float) -> Tuple[int, int, int]:
        """
        ARCHITECTURE_MASTER_V24: Retourne la couleur de fond exacte par fenêtre.

        Mesures:
            Inversion #1 (t≈12-12.79s) : bg = rgb(0,0,0) pur noir
            Inversion #2 (t≈40.2-fin)  : bg = rgb(14,14,26) navy profond
        """
        # Fenêtre 2 : dark navy (après t=40.2s)
        if t >= 40.20:
            return INVERSION_BG_COLOR_2   # (14, 14, 26)
        # Fenêtre 1 et tout autre cas : pur noir
        return INVERSION_BG_COLOR_1       # (0, 0, 0)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5 — B-Roll Card (V24: position corrigée)
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
        ARCHITECTURE_MASTER_V24: Card B-Roll positionnée à 0.663H.

        CORRECTION MAJEURE vs V23:
            V23: cy_base = vid_h * 0.4717 → card au centre (INCORRECT)
            V24: cy_base = vid_h * 0.663  → card dans la moitié basse (CORRECT)

        Layout résultant (1080×1920):
            Card center Y = 1920 * 0.663 = 1273px
            Card top      = 1273 - card_h/2 ≈ 932px  (0.485H)
            Card bottom   = 1273 + card_h/2 ≈ 1615px (0.841H)
            Texte centre  = 1920 * 0.4985 = 957px     (0.499H)

            → Légère superposition texte/card au niveau du bord supérieur
              de la card (957 vs 932 = 25px de chevauchement intentionnel)
            → Le texte (z=10) apparaît AU-DESSUS de la card (z=5)

        Pipeline spring entry:
            Slide depuis Y+8px, alpha 0→1 en 3-4 frames (99-132ms @30fps)
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

        # ARCHITECTURE_MASTER_V24: BROLL_CARD_CENTER_Y_RATIO = 0.663 (corrigé)
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
            z_index     = 5,   # Derrière le texte (z=10)
            tag         = "broll_card",
        ))

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — Smart Layout V24 (texte fixe — rupture avec V23)
    # ══════════════════════════════════════════════════════════════════════

    def _compute_text_y_for_time(
        self,
        t:              float,
        broll_schedule: List[Tuple[float, float, str]],
    ) -> int:
        """
        ARCHITECTURE_MASTER_V24: Ancrage Y du texte.

        CORRECTION CENTRALE: Le texte NE SE DÉPLACE PAS.
        Retourne toujours self._text_cy (= VID_H × 0.4985).

        Historique:
            V22: Texte fixe (correct)
            V23: Texte se déplace à 0.72H quand B-Roll actif (INCORRECT)
            V24: Texte fixe à 0.4985H (retour au comportement correct mesuré)

        La card se positionne SOUS le texte (0.663H) sans
        perturber l'ancrage du texte.

        Note: broll_schedule est conservé en paramètre pour extensibilité
        future (ex: si un mode spécial nécessite le déplacement du texte).
        Pour l'instant: BROLL_TEXT_STAYS_PUT = True dans config.py.
        """
        # ARCHITECTURE_MASTER_V24: Retourne toujours le centre fixe
        return self._text_cy

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7 — BURN PRINCIPAL (V24)
    # ══════════════════════════════════════════════════════════════════════

    def burn_subtitles(
        self,
        video_clip,
        timeline:       List[Tuple[float, float, str]],
        broll_schedule: List[Tuple[float, float, str]] = None,
    ):
        """
        ARCHITECTURE_MASTER_V24: Point d'entrée principal.

        Différences vs V23:
            - Texte reste à 0.4985H (ne bouge plus avec B-Roll)
            - B-Roll card à 0.663H (corrigé depuis 0.4717H)
            - Couleurs bg inversion par fenêtre (noir pur vs navy)
            - Timestamps inversion: (12.0,12.79) et (40.2,44.1)

        Pipeline V24:
            1. split_to_single_words → 1 mot/entrée
            2. _build_word_clip (y_anchor = _text_cy, FIXE)
            3. TimelineEngine.add() pour chaque WordClip
            4. _build_broll_timelineobject() → card à 0.663H
            5. _compute_inversion_intervals() timestamps V24
            6. make_frame(t):
               a. Base frame
               b. Inversion bg avec couleur par fenêtre
               c. B-Roll cards via TimelineEngine (z=5)
               d. Texte via compose_frame (z=10, toujours visible au-dessus)
               e. Zoom global 1.00→1.03
        """
        if not MOVIEPY_AVAILABLE:
            print("⚠️  moviepy indisponible — burn_subtitles retourne clip original")
            return video_clip
        if not timeline:
            print("⚠️  [V24] Timeline vide — aucun sous-titre brûlé")
            return video_clip

        broll_schedule = broll_schedule or []

        # ── Étape 1: 1 mot par entrée ─────────────────────────────────────
        words = split_to_single_words(timeline)
        print(f"🎬 V24 Pipeline: {len(timeline)} entrées → {len(words)} mots")
        if broll_schedule:
            print(f"  📸 B-Roll schedule: {len(broll_schedule)} cards")
            print(f"  📌 Layout: texte FIXE à {TEXT_ANCHOR_Y_RATIO}H, cards à {BROLL_CARD_CENTER_Y_RATIO}H")

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        scale_x = vid_w / self.VID_W
        scale_y = vid_h / self.VID_H
        scaled  = abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01
        if scaled:
            print(f"📐 V24: Rescaling {self.VID_W}×{self.VID_H} → {vid_w}×{vid_h}")

        # ARCHITECTURE_MASTER_V24: Un seul ancrage Y pour le texte
        actual_text_cy = int(self._text_cy * scale_y)

        # ── Étape 2: TimelineEngine ───────────────────────────────────────
        engine = TimelineEngine(width=vid_w, height=vid_h)

        # ── Étape 3: Construire WordClips ─────────────────────────────────
        all_word_clips: List[WordClip] = []
        for t_start, t_end, word in words:
            # ARCHITECTURE_MASTER_V24: y_anchor TOUJOURS = actual_text_cy
            # _compute_text_y_for_time() retourne toujours self._text_cy
            y_anchor = actual_text_cy

            wclip = self._build_word_clip(word, t_start, t_end, y_anchor=y_anchor)
            if wclip is None:
                continue

            if scaled:
                wclip.target_x = int(wclip.target_x * scale_x)
                wclip.target_y = int(wclip.target_y * scale_y)

            all_word_clips.append(wclip)

        if not all_word_clips:
            print("⚠️  Aucun WordClip valide")
            return video_clip

        print(f"✅ V24: {len(all_word_clips)} WordClips (ancrage Y fixe: {actual_text_cy}px = {TEXT_ANCHOR_Y_RATIO}H)")

        # ── Étape 4: B-Roll cards dans le TimelineEngine (z=5) ───────────
        # ARCHITECTURE_MASTER_V24: Cards positionnées à 0.663H (sous le texte)
        for t_bs, t_be, img_path in broll_schedule:
            self._build_broll_timelineobject(
                image_path = img_path,
                t_start    = t_bs,
                t_end      = t_be,
                engine     = engine,
                vid_w      = vid_w,
                vid_h      = vid_h,
            )
            card_center_px = int(vid_h * BROLL_CARD_CENTER_Y_RATIO)
            print(f"  📸 Card t=[{t_bs:.2f},{t_be:.2f}s] → center_y={card_center_px}px ({BROLL_CARD_CENTER_Y_RATIO}H)")

        # ── Étape 5: Intervalles d'inversion (V24 timestamps) ────────────
        inv_intervals = self._compute_inversion_intervals(all_word_clips, duration)
        if inv_intervals:
            print(f"🎨 V24: {len(inv_intervals)} inversion(s): {[(f'{t0:.2f}s', f'{t1:.2f}s') for t0,t1 in inv_intervals]}")

        # ── Étape 6: make_frame ───────────────────────────────────────────
        last_valid_frame = None

        def make_frame(t: float) -> np.ndarray:
            nonlocal last_valid_frame

            # Frame source (fond blanc)
            try:
                base = video_clip.get_frame(t)
                last_valid_frame = base
            except Exception:
                base = (last_valid_frame if last_valid_frame is not None
                        else np.full((vid_h, vid_w, 3), 255, dtype=np.uint8))

            # Détection inversion
            is_inv = any(t0 <= t < t1 for t0, t1 in inv_intervals)

            if is_inv:
                # ARCHITECTURE_MASTER_V24: Couleur bg par fenêtre (mesuré)
                bg_color = self._get_inversion_bg_color(t)
                base = np.full_like(base, 0)
                base[:,:,0] = bg_color[0]
                base[:,:,1] = bg_color[1]
                base[:,:,2] = bg_color[2]

            # ÉTAPE A — B-Roll cards via TimelineEngine (z=5, derrière texte)
            frame = engine.render_frame(t, base)

            # ÉTAPE B — Texte via compose_frame (z=10, au-dessus des cards)
            frame = compose_frame(
                t, all_word_clips, vid_w, vid_h,
                base_frame=frame, inverted=is_inv,
            )

            # ÉTAPE C — Zoom global 1.00→1.03 ease_in_out_sine
            p          = EasingLibrary.ease_in_out_sine(t / max(duration, 1e-6))
            zoom_scale = GLOBAL_ZOOM_START + (GLOBAL_ZOOM_END - GLOBAL_ZOOM_START) * p
            frame      = apply_continuous_zoom(frame, zoom_scale)

            return frame

        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)
        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 8 — Whisper Transcription (inchangée)
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

        print(f"🎤 Whisper V24: {len(all_words)} mots transcrits")
        return all_words

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 9 — Rétrocompatibilité
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
Title: Nexus V24
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