# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/scene_animator.py
"""
NEXUS SCENE ANIMATOR V9 — TEKIYO LIVING BACKGROUNDS
Rapport des améliorations V8 → V9 :

  Étape 1 – Direction Artistique :
    · Fond blanc #FFFFFF en priorité absolue.
    · Nouvelles courbes Bézier : ease_in_expo, ease_out_back (élasticité)
    · Palette étendue : ombres portées douces (neumorphisme léger)

  Étape 2 – Maîtrise du Mouvement :
    · apply_micro_zoom_continuous() : micro-zoom frame par frame
    · Slide transition améliorée avec ease_out_back pour effet "snap & glide"
    · Continuité visuelle : transition FADE entre scènes du même sujet

  Étape 3 – Métaphores Visuelles :
    · create_ui_price_card() : badge prix / % neumorphique avec ombre portée
    · create_repeater_matrix() : matrice de répétition géométrique modifiée pour extension
    · NOUVEAU V9 -> create_animated_repeater_clip() : Matrice vivante (glissement diagonal)
    · apply_underline_draw_frame() : underline animé qui se "dessine" de G→D
"""
from moviepy.editor import ImageClip, CompositeVideoClip, VideoClip
import random
import math
import numpy as np
import os
import tempfile
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageFont


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


class SceneAnimator:
    """
    NEXUS Scene Animator V9 — Premium Motion Mode.
    Transforme des images statiques en séquences dynamiques premium.
    """

    # Couleurs de fond (sélection via create_background())
    WHITE_BG_COLOR = (255, 255, 255)    # #FFFFFF — premium, neutre absolu
    CREAM_BG_COLOR = (245, 245, 247)    # #F5F5F7 — Apple crème (option)

    # Ombres portées (neumorphisme léger)
    SHADOW_COLOR   = (200, 200, 205, 80)   # RGBA — ombre très douce

    def __init__(self, width: int = 1080, height: int = 1920):
        self.W        = width
        self.H        = height
        self.temp_dir = tempfile.gettempdir()

    # =========================================================================
    # COURBES DE BÉZIER — ARSENAL COMPLET
    # =========================================================================

    @staticmethod
    def _ease_out_cubic(p: float) -> float:
        """Décélération douce — standard."""
        return 1.0 - (1.0 - max(0.0, min(1.0, p))) ** 3

    @staticmethod
    def _ease_in_out_sine(p: float) -> float:
        """Accélération et décélération sinusoïdale."""
        return -(math.cos(math.pi * p) - 1) / 2

    @staticmethod
    def _ease_in_expo(p: float) -> float:
        """
        Départ quasi-nul puis explosion — idéal pour les entrées "snap".
        Donne cette sensation de clic instantané avant le freinage.
        """
        p = max(0.0, min(1.0, p))
        if p == 0.0:
            return 0.0
        return 2.0 ** (10.0 * (p - 1.0))

    @staticmethod
    def _ease_out_expo(p: float) -> float:
        """Décélération exponentielle — arrêt très précis."""
        p = max(0.0, min(1.0, p))
        if p == 1.0:
            return 1.0
        return 1.0 - 2.0 ** (-10.0 * p)

    @staticmethod
    def _ease_out_back(p: float, overshoot: float = 1.70158) -> float:
        """
        Dépasse légèrement la cible puis revient — effet élastique premium.
        overshoot=1.70 → discret ; overshoot=2.5 → prononcé.
        """
        p = max(0.0, min(1.0, p))
        c1 = overshoot
        c3 = c1 + 1.0
        return 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2

    @staticmethod
    def _ease_in_out_spring(p: float) -> float:
        """
        Courbe spring : démarrage rapide, rebond léger en fin de course.
        Idéale pour les slide transitions entre sujets différents.
        """
        p = max(0.0, min(1.0, p))
        if p < 0.5:
            return 4.0 * p * p * p
        else:
            f = (2.0 * p - 2.0)
            return 0.5 * f * f * f + 1.0

    # =========================================================================
    # HELPERS INTERNES
    # =========================================================================

    @staticmethod
    def _ease_out(p: float) -> float:
        """Alias court pour ease_out_cubic."""
        return SceneAnimator._ease_out_cubic(p)

    def _get_interest_center(self, image_path: str) -> tuple:
        """Détecte le centre visuel d'intérêt par analyse de contraste (saliency)."""
        try:
            with Image.open(image_path) as img:
                small = img.resize((100, 100)).convert("L")
                arr   = np.array(small)
                h, w  = arr.shape
                best_score  = -1
                best_center = (0.5, 0.5)

                for r in range(3):
                    for c in range(3):
                        sub   = arr[r * (h // 3):(r + 1) * (h // 3),
                                    c * (w // 3):(c + 1) * (w // 3)]
                        score = np.std(sub)
                        if score > best_score:
                            best_score  = score
                            best_center = ((c + 0.5) / 3.0, (r + 0.5) / 3.0)
                return best_center
        except Exception as e:
            print(f"Saliency Warning: {e}")
            return (0.5, 0.5)

    def _determine_mood(self, keywords: str) -> str:
        k = keywords.lower()
        if any(x in k for x in ["crash", "chute", "danger", "stop", "perte",
                                  "alerte", "scam", "urgent", "attention"]):
            return "URGENT"
        if any(x in k for x in ["profit", "gain", "hausse", "moon", "succès",
                                  "argent", "croissance", "résultat", "million"]):
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

    # =========================================================================
    # FONDS
    # =========================================================================

    def create_background(self, output_path: str, style: str = "white") -> str:
        """
        Génère le fond premium.
        style='white' → #FFFFFF (défaut, neutre absolu, luxueux)
        style='cream' → #F5F5F7 (Apple, option chaude)
        """
        color = self.WHITE_BG_COLOR if style == "white" else self.CREAM_BG_COLOR
        img   = Image.new("RGB", (self.W, self.H), color=color)
        img.save(output_path, quality=98)
        return output_path

    def create_cream_background(self, output_path: str) -> str:
        """Rétrocompatibilité — délègue à create_background(style='cream')."""
        return self.create_background(output_path, style="cream")

    # =========================================================================
    # MUTATION VISUELLE
    # =========================================================================

    def _apply_visual_mutation(self, image_path: str) -> str:
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                if random.random() > 0.5:
                    img = ImageOps.mirror(img)
                for enhancer_cls, delta in [
                    (ImageEnhance.Brightness, 0.02),
                    (ImageEnhance.Contrast,   0.02),
                ]:
                    factor = 1.0 + random.uniform(-delta, delta)
                    img    = enhancer_cls(img).enhance(factor)
                w, h   = img.size
                margin = min(w, h) * 0.01
                img    = img.crop((margin, margin, w - margin, h - margin))
                temp_path = os.path.join(
                    self.temp_dir,
                    f"mutated_{random.randint(10000, 99999)}.jpg"
                )
                img.save(temp_path, quality=95)
                return temp_path
        except Exception as e:
            print(f"Mutation Failed: {e}, using original.")
            return image_path

    # =========================================================================
    # CLIP DYNAMIQUE DE BASE
    # =========================================================================

    def create_dynamic_clip(
        self,
        image_path,
        duration: float = 5.0,
        context_keywords: str = "",
        scene_context: SceneContext = None,
        apply_mutation: bool = False
    ):
        if scene_context is None:
            scene_context = SceneContext()

        working_path = image_path
        if apply_mutation:
            working_path = self._apply_visual_mutation(str(image_path))
            duration    += random.uniform(-0.1, 0.1)

        mood        = self._determine_mood(context_keywords)
        motion_type = self._decide_motion_strategy(mood, scene_context)
        scene_context.update(motion_type)

        target_x_ratio, target_y_ratio = self._get_interest_center(str(working_path))

        zoom_factors = {
            "ZOOM_IN_HARD": 1.05,
            "ZOOM_IN":      1.03,
            "ZOOM_OUT":     1.04,
            "STATIC":       1.00,
            "PAN_SLOW":     1.05,
        }
        zoom_factor = zoom_factors.get(motion_type, 1.02)

        try:
            img = ImageClip(str(working_path)).set_duration(duration)
        except Exception:
            img = ImageClip(str(image_path)).set_duration(duration)

        img_w, img_h   = img.size
        ratio_canvas   = self.W / self.H
        ratio_img      = img_w / img_h
        new_h          = self.H * zoom_factor
        new_w          = self.W * zoom_factor

        if ratio_img > ratio_canvas:
            final_h = new_h
            final_w = final_h * ratio_img
        else:
            final_w = new_w
            final_h = final_w / ratio_img

        img = img.resize(width=final_w) if final_w > final_h * ratio_img \
              else img.resize(height=int(final_h))

        x_overflow = img.w - self.W
        y_overflow = img.h - self.H

        ideal_x    = (self.W / 2) - (target_x_ratio * img.w)
        ideal_y    = (self.H / 2) - (target_y_ratio * img.h)

        focus_x    = max(-x_overflow, min(0, ideal_x))
        focus_y    = max(-y_overflow, min(0, ideal_y))
        center_x   = -x_overflow / 2
        center_y   = -y_overflow / 2

        start_x, start_y = center_x, center_y
        dest_x,  dest_y  = center_x, center_y

        if "ZOOM_IN" in motion_type:
            dest_x, dest_y = focus_x, focus_y
        elif motion_type == "ZOOM_OUT":
            start_x, start_y = focus_x, focus_y
        elif motion_type == "PAN_SLOW":
            if x_overflow > y_overflow:
                start_x = 0 if focus_x < center_x else -x_overflow
                dest_x  = -x_overflow if focus_x < center_x else 0
            else:
                start_y = 0
                dest_y  = -y_overflow

        def position_func(t):
            if motion_type == "STATIC":
                return (int(center_x), int(center_y))
            progress = t / duration
            p = (progress * progress * progress if motion_type == "ZOOM_IN_HARD"
                 else progress if motion_type == "PAN_SLOW"
                 else -1 * progress * (progress - 2))
            return (int(start_x + (dest_x - start_x) * p),
                    int(start_y + (dest_y - start_y) * p))

        img = img.set_position(position_func)
        return CompositeVideoClip([img], size=(self.W, self.H))

    def create_scene(
        self,
        image_path,
        duration: float,
        effect=None,
        resolution=None,
        apply_mutation: bool = False
    ):
        return self.create_dynamic_clip(
            image_path,
            duration=duration,
            apply_mutation=apply_mutation
        )

    # =========================================================================
    # SLOW ZOOM GLOBAL
    # =========================================================================

    def apply_global_slowzoom(
        self,
        clip,
        start_scale: float = 1.0,
        end_scale:   float = 1.05
    ):
        duration = clip.duration
        w_out, h_out = self.W, self.H

        def zoom_frame(get_frame, t):
            progress = t / duration if duration > 0 else 0
            eased    = self._ease_in_out_sine(progress)
            scale    = start_scale + (end_scale - start_scale) * eased
            frame    = get_frame(t)
            fh, fw   = frame.shape[:2]
            new_w    = max(fw, int(fw * scale))
            new_h    = max(fh, int(fh * scale))

            try:
                from PIL import Image as PILImg
                img  = PILImg.fromarray(frame).resize((new_w, new_h), PILImg.LANCZOS)
                arr  = np.array(img)
                y0   = (new_h - fh) // 2
                x0   = (new_w - fw) // 2
                return arr[y0:y0 + fh, x0:x0 + fw]
            except Exception:
                return frame

        return clip.fl(zoom_frame)

    # =========================================================================
    # MICRO-ZOOM CONTINU PAR SCÈNE
    # =========================================================================

    def apply_micro_zoom_continuous(
        self,
        clip,
        intensity: float = 0.008
    ):
        duration = clip.duration

        def micro_zoom_frame(get_frame, t):
            progress = t / duration if duration > 0 else 0
            eased    = self._ease_in_out_sine(progress)
            scale    = 1.0 + intensity * eased
            frame    = get_frame(t)
            fh, fw   = frame.shape[:2]
            new_w    = max(fw, int(fw * scale))
            new_h    = max(fh, int(fh * scale))

            try:
                from PIL import Image as PILImg
                img  = PILImg.fromarray(frame).resize((new_w, new_h), PILImg.LANCZOS)
                arr  = np.array(img)
                y0   = (new_h - fh) // 2
                x0   = (new_w - fw) // 2
                return arr[y0:y0 + fh, x0:x0 + fw]
            except Exception:
                return frame

        return clip.fl(micro_zoom_frame)

    # =========================================================================
    # SLIDE TRANSITION
    # =========================================================================

    def create_slide_transition(
        self,
        clip_out,
        clip_in,
        transition_duration: float = 0.30,
        direction: str = "left",
        spring: bool = True
    ):
        td = transition_duration

        direction_vectors = {
            "left":  (-self.W,  0),
            "right": ( self.W,  0),
            "up":    ( 0, -self.H),
            "down":  ( 0,  self.H),
        }
        dx, dy = direction_vectors.get(direction, (-self.W, 0))

        ease_fn = self._ease_out_back if spring else self._ease_out_cubic

        def make_out_pos(t):
            p    = min(t / td, 1.0)
            ease = self._ease_out_cubic(p)
            return (int(dx * ease), int(dy * ease))

        def make_in_pos(t):
            p    = min(t / td, 1.0)
            ease = ease_fn(p)
            return (int(-dx * (1.0 - ease)), int(-dy * (1.0 - ease)))

        out_clip = (
            clip_out
            .set_duration(td)
            .set_position(make_out_pos)
        )
        in_clip = (
            clip_in
            .set_duration(td)
            .set_position(make_in_pos)
        )

        return CompositeVideoClip(
            [out_clip, in_clip],
            size=(self.W, self.H)
        ).set_duration(td)

    # =========================================================================
    # FADE TRANSITION
    # =========================================================================

    def create_fade_transition(
        self,
        clip_out,
        clip_in,
        transition_duration: float = 0.10
    ):
        td = transition_duration

        def fade_out_frame(get_frame, t):
            p     = min(t / td, 1.0)
            alpha = 1.0 - self._ease_in_out_sine(p)
            return (get_frame(t).astype(np.float32) * alpha).astype(np.uint8)

        def fade_in_frame(get_frame, t):
            p     = min(t / td, 1.0)
            alpha = self._ease_in_out_sine(p)
            return (get_frame(t).astype(np.float32) * alpha).astype(np.uint8)

        out_faded = clip_out.set_duration(td).fl(fade_out_frame)
        in_faded  = clip_in.set_duration(td).fl(fade_in_frame)

        return CompositeVideoClip(
            [out_faded, in_faded],
            size=(self.W, self.H)
        ).set_duration(td)

    # =========================================================================
    # MOTION BLUR
    # =========================================================================

    def apply_motion_blur(
        self,
        clip,
        strength:    float = 0.35,
        num_samples: int   = 2
    ):
        fps = clip.fps or 30.0

        def blur_frame(get_frame, t):
            current = get_frame(t).astype(np.float32)
            if t == 0:
                return current.astype(np.uint8)
            result = current * (1.0 - strength)
            try:
                prev   = get_frame(max(0, t - 1.0 / fps)).astype(np.float32)
                result += prev * strength
            except Exception:
                return current.astype(np.uint8)
            if num_samples >= 2 and t > 1.0 / fps:
                try:
                    prev2  = get_frame(max(0, t - 2.0 / fps)).astype(np.float32)
                    w1, w2 = strength * 0.6, strength * 0.4
                    result = (current * (1.0 - strength) +
                               prev    * w1 +
                               prev2   * w2)
                except Exception:
                    pass
            return np.clip(result, 0, 255).astype(np.uint8)

        return clip.fl(blur_frame)

    # =========================================================================
    # BADGE PRIX / % NEUMORPHIQUE
    # =========================================================================

    def create_ui_price_card(
        self,
        text: str,
        width: int = None,
        bg_color: tuple = (255, 255, 255),
        accent_color: tuple = (123, 44, 191),   # Violet premium
        font_path: str = None
    ) -> np.ndarray:
        if width is None:
            width = int(self.W * 0.55)

        pad_h, pad_v, radius = 48, 32, 32
        font_size = 88

        candidates = [
            font_path,
            "Inter-ExtraBold.ttf", "Inter_ExtraBold.ttf",
            "Montserrat-ExtraBold.ttf", "Poppins-Bold.ttf",
            "arial.ttf", "Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
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
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 45, 60

        cw = min(tw + pad_h * 2, width)
        ch = th + pad_v * 2 + 8
        r  = min(radius, ch // 2)

        canvas = Image.new("RGBA", (cw + 12, ch + 12), (0, 0, 0, 0))
        draw   = ImageDraw.Draw(canvas)

        shadow_offset = 6
        shadow_col    = (180, 180, 185, 120)
        draw.rounded_rectangle(
            [shadow_offset, shadow_offset, cw + shadow_offset - 1, ch + shadow_offset - 1],
            radius=r, fill=shadow_col
        )

        highlight_col = (255, 255, 255, 200)
        draw.rounded_rectangle(
            [-2, -2, cw - 2, ch - 2],
            radius=r, fill=highlight_col
        )

        draw.rounded_rectangle(
            [0, 0, cw - 1, ch - 1],
            radius=r, fill=bg_color + (255,) if len(bg_color) == 3 else bg_color
        )

        tx = (cw - tw) // 2
        ty = pad_v
        draw.text((tx, ty), text, font=pil_font, fill=accent_color + (255,))

        return np.array(canvas)

    # =========================================================================
    # MATRICE DE RÉPÉTITION (Dynamisée pour la V9)
    # =========================================================================

    def create_repeater_matrix(
        self,
        element_path: str,
        cols: int = 8,
        rows: int = 14,
        output_path: str = None,
        opacity: float = 0.12,
        bg_color: tuple = (255, 255, 255),
        canvas_w: int = None,
        canvas_h: int = None
    ) -> str:
        """
        Crée une composition matricielle massive avec répéteur géométrique.
        """
        if output_path is None:
            output_path = os.path.join(
                self.temp_dir,
                f"repeater_{random.randint(10000, 99999)}.png"
            )

        cw = canvas_w or self.W
        ch = canvas_h or self.H

        canvas = Image.new("RGBA", (cw, ch), bg_color + (255,))

        cell_w = cw // cols
        cell_h = ch // rows

        try:
            elem = Image.open(element_path).convert("RGBA")
        except Exception:
            # Fallback : point géométrique simple
            elem = Image.new("RGBA", (20, 20), (29, 29, 31, 255))

        # Redimensionne l'élément pour tenir dans une cellule avec padding
        pad     = 0.75
        max_w   = int(cell_w * pad)
        max_h   = int(cell_h * pad)
        elem.thumbnail((max_w, max_h), Image.LANCZOS)

        # Applique l'opacité
        if opacity < 1.0:
            r, g, b, a = elem.split()
            a = a.point(lambda x: int(x * opacity))
            elem = Image.merge("RGBA", (r, g, b, a))

        # Placement en grille avec offset alterné (brickwork pattern)
        for row in range(rows):
            for col in range(cols):
                offset_x = (cell_w // 4) if row % 2 == 1 else 0
                x = col * cell_w + (cell_w - elem.width) // 2 + offset_x
                y = row * cell_h + (cell_h - elem.height) // 2
                canvas.paste(elem, (x, y), mask=elem.split()[3])

        canvas.convert("RGB").save(output_path, quality=95)
        return output_path

    # =========================================================================
    # ★ NOUVEAU V9 : MATRICE ANIMÉE
    # =========================================================================

    def create_animated_repeater_clip(
        self,
        element_path: str,
        duration: float,
        cols: int = 8,
        rows: int = 14,
        opacity: float = 0.12,
        bg_color: tuple = (255, 255, 255)
    ):
        """
        Nouveauté V9 : Crée la matrice, mais la génère 30% plus grande
        puis applique un glissement (Pan) diagonal doux pour donner la vie.
        """
        # On agrandit la toile virtuelle pour permettre le glissement sans voir les bords
        oversize_w = int(self.W * 1.3)
        oversize_h = int(self.H * 1.3)
        oversize_cols = int(cols * 1.3)
        oversize_rows = int(rows * 1.3)

        matrix_path = self.create_repeater_matrix(
            element_path=element_path,
            cols=oversize_cols,
            rows=oversize_rows,
            opacity=opacity,
            bg_color=bg_color,
            canvas_w=oversize_w,
            canvas_h=oversize_h
        )

        clip = ImageClip(matrix_path).set_duration(duration)

        # Mouvement en diagonale subtil
        x_overflow = oversize_w - self.W
        y_overflow = oversize_h - self.H

        def moving_matrix(t):
            progress = t / duration if duration > 0 else 0
            ease = self._ease_in_out_sine(progress)
            
            x = int(-x_overflow * 0.8 * ease)
            y = int(-y_overflow * 0.8 * ease)
            return (x, y)

        return CompositeVideoClip([clip.set_position(moving_matrix)], size=(self.W, self.H))

    # =========================================================================
    # UNDERLINE ANIMÉ (dessin G→D)
    # =========================================================================

    def create_underline_draw_frame(
        self,
        frame: np.ndarray,
        progress: float,
        y_pos: int,
        x_start: int,
        x_end: int,
        color: tuple = (123, 44, 191),
        thickness: int = 6
    ) -> np.ndarray:
        """
        Dessine un underline progressif sur un frame numpy.
        """
        img    = Image.fromarray(frame)
        draw   = ImageDraw.Draw(img)
        eased  = max(0.0, min(1.0, progress))
        x_curr = int(x_start + (x_end - x_start) * eased)

        if x_curr > x_start:
            # Ligne principale
            draw.line(
                [(x_start, y_pos), (x_curr, y_pos)],
                fill=color, width=thickness
            )
            # Sous-ligne semi-transparente (ombre portée)
            draw.line(
                [(x_start, y_pos + 3), (x_curr, y_pos + 3)],
                fill=color + (80,) if len(color) == 3 else color,
                width=max(1, thickness // 3)
            )

        return np.array(img)

    # =========================================================================
    # HELPERS TRANSITION INTELLIGENTE
    # =========================================================================

    def should_slide_transition(self, prev_keywords: str, curr_keywords: str) -> bool:
        """Slide si changement de sujet, Fade si même sujet."""
        return self._determine_mood(prev_keywords) != self._determine_mood(curr_keywords)

    def should_fade_transition(self, prev_keywords: str, curr_keywords: str) -> bool:
        """Fade si même sujet (complément de should_slide_transition)."""
        return not self.should_slide_transition(prev_keywords, curr_keywords)

    def get_slide_direction(self, scene_index: int) -> str:
        """Alterne les directions de slide pour varier les transitions."""
        directions = ["left", "up", "left", "down"]
        return directions[scene_index % len(directions)]