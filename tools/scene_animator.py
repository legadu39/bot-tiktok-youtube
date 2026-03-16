# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V29: SceneAnimator — positions broll DÉFINITIVES.
#
# DELTA V29 vs V22:
#   1. create_broll_card_clip(): center_y_ratio 0.614 → 0.471 (mesuré content center)
#   2. create_broll_card_clip(): corner_radius ratio 0.064 → 0.036 (39px@1080p mesuré)
#   3. create_broll_card_clip(): width ratio 0.524 → 0.530 (305/576 mesuré)
#   4. Tous les paramètres héritent de config.py V29

from __future__ import annotations

import math
import os
import random
import tempfile
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoClip
    MOVIEPY_OK = True
except ImportError:
    MOVIEPY_OK = False

from .easing    import EasingLibrary
from .physics   import SpringPhysics
from .effects   import EffectBase, EffectContinuousZoom, EffectSpringOvershoot
from .timeline  import TimelineObject, TimelineEngine
from .graphics  import render_broll_card, find_font
from .config    import (
    BROLL_CARD_WIDTH_RATIO, BROLL_CARD_RADIUS_RATIO,
    BROLL_CARD_CENTER_Y_RATIO,
    GLOBAL_ZOOM_START, GLOBAL_ZOOM_END,
    BROLL_SHADOW_BLUR, BROLL_SHADOW_OPACITY,
    SPRING_STIFFNESS, SPRING_DAMPING, SPRING_SLIDE_PX,
    WHITE_BG_COLOR, CREAM_BG_COLOR,
)


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
    ARCHITECTURE_MASTER_V29: Gestionnaire de scènes vidéo.

    Corrections V29:
        • B-Roll card center Y : H×0.471 (V29 CORRIGÉ — content center mesuré)
        • B-Roll corner radius : canvas×0.036 (V29 CORRIGÉ — 39px@1080p)
        • B-Roll width ratio   : canvas×0.530 (V29 CORRIGÉ — 305/576 mesuré)
    """

    _ease = EasingLibrary

    def __init__(self, width: int = 1080, height: int = 1920):
        self.W        = width
        self.H        = height
        self.temp_dir = tempfile.gettempdir()

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
    def _ease_out(p): return EasingLibrary.ease_out_cubic(p)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — Backgrounds
    # ══════════════════════════════════════════════════════════════════════

    def create_background(self, output_path: str, style: str = "white") -> str:
        color = WHITE_BG_COLOR if style == "white" else CREAM_BG_COLOR
        img   = Image.new("RGB", (self.W, self.H), color=color)
        img.save(output_path, quality=98)
        return output_path

    def create_cream_background(self, output_path: str) -> str:
        return self.create_background(output_path, style="cream")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2 — Dynamic Clip (Motion)
    # ══════════════════════════════════════════════════════════════════════

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
                            best_center = ((c + 0.5) / 3.0, (r + 0.5) / 3.0)
                return best_center
        except Exception:
            return (0.5, 0.5)

    def _determine_mood(self, keywords: str) -> str:
        k = keywords.lower()
        if any(x in k for x in ["crash","danger","stop","perte","alerte","scam","urgent"]):
            return "URGENT"
        if any(x in k for x in ["profit","gain","hausse","succès","argent","million"]):
            return "GROWTH"
        return "NEUTRAL"

    def _decide_motion(self, mood: str, context: SceneContext) -> str:
        if mood == "URGENT":
            return "ZOOM_IN_HARD" if context.consecutive_count < 3 else "ZOOM_IN"
        if context.last_motion in ["ZOOM_IN", "ZOOM_IN_HARD"]:
            return random.choice(["STATIC", "ZOOM_OUT"])
        if context.last_motion in ["STATIC", "ZOOM_OUT"]:
            return "ZOOM_IN"
        return "STATIC"

    def create_dynamic_clip(
        self,
        image_path,
        duration:         float       = 5.0,
        context_keywords: str         = "",
        scene_context:    SceneContext = None,
        apply_mutation:   bool        = False,
    ):
        if not MOVIEPY_OK:
            raise ImportError("moviepy requis")
        if scene_context is None:
            scene_context = SceneContext()

        working = self._apply_visual_mutation(str(image_path)) if apply_mutation else image_path
        if apply_mutation:
            duration += random.uniform(-0.1, 0.1)

        mood        = self._determine_mood(context_keywords)
        motion_type = self._decide_motion(mood, scene_context)
        scene_context.update(motion_type)

        tx, ty = self._get_interest_center(str(working))

        zoom_f = {
            "ZOOM_IN_HARD": 1.05, "ZOOM_IN": 1.03,
            "ZOOM_OUT": 1.04, "STATIC": 1.00, "PAN_SLOW": 1.05,
        }
        zf = zoom_f.get(motion_type, 1.02)

        try:
            img = ImageClip(str(working)).set_duration(duration)
        except Exception:
            img = ImageClip(str(image_path)).set_duration(duration)

        img_w, img_h  = img.size
        ratio_canvas  = self.W / self.H
        ratio_img     = img_w / img_h
        new_h, new_w  = self.H * zf, self.W * zf

        if ratio_img > ratio_canvas:
            final_h = new_h
            final_w = final_h * ratio_img
        else:
            final_w = new_w
            final_h = final_w / ratio_img

        img = (img.resize(width=int(final_w))
               if final_w > final_h * ratio_img
               else img.resize(height=int(final_h)))

        xov     = img.w - self.W
        yov     = img.h - self.H
        ideal_x = (self.W / 2) - (tx * img.w)
        ideal_y = (self.H / 2) - (ty * img.h)
        focus_x = max(-xov, min(0, ideal_x))
        focus_y = max(-yov, min(0, ideal_y))
        cx, cy  = -xov / 2, -yov / 2
        sx, sy  = cx, cy
        dx, dy  = cx, cy

        if "ZOOM_IN" in motion_type: dx, dy = focus_x, focus_y
        elif motion_type == "ZOOM_OUT": sx, sy = focus_x, focus_y
        elif motion_type == "PAN_SLOW":
            if xov > yov: sx, dx = (0 if focus_x < cx else -xov), (-xov if focus_x < cx else 0)
            else:         sy, dy = 0, -yov

        def pos_fn(t):
            if motion_type == "STATIC": return (int(cx), int(cy))
            p = t / max(duration, 1e-6)
            p = (p**3 if motion_type == "ZOOM_IN_HARD"
                 else p if motion_type == "PAN_SLOW"
                 else -p * (p - 2))
            return (int(sx + (dx - sx) * p), int(sy + (dy - sy) * p))

        img = img.set_position(pos_fn)
        return CompositeVideoClip([img], size=(self.W, self.H))

    def create_scene(self, image_path, duration=5.0, effect=None, resolution=None, apply_mutation=False):
        return self.create_dynamic_clip(image_path, duration=duration, apply_mutation=apply_mutation)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3 — B-Roll Card (V29: toutes valeurs CORRIGÉES)
    # ══════════════════════════════════════════════════════════════════════

    def create_broll_card_clip(
        self,
        image_path: str,
        duration:   float,
        t_appear:   float         = 0.0,
        spring:     SpringPhysics = None,
        card_width_ratio: float   = None,
    ):
        """
        ARCHITECTURE_MASTER_V29: B-Roll card avec toutes corrections V29.

        MESURES DÉFINITIVES (frame t=8s, 576×1024):
        ─────────────────────────────────────────────
        Content rows=[402,562] → center = 482/1024 = 0.4707H → 0.471
        Content cols=[135,440] → width  = 305/576  = 0.530
        Corner radius tracé   → 21px@576p = 39px@1080p → 0.036W

        Spring: k=900, c=30, ζ=0.50, settle 200ms = 6 frames @30fps
        """
        if not MOVIEPY_OK:
            raise ImportError("moviepy requis")

        sp = spring or SpringPhysics(SPRING_STIFFNESS, SPRING_DAMPING)

        card_arr  = render_broll_card(
            image_path    = image_path,
            canvas_w      = self.W,
            corner_radius = None,
            shadow_blur   = BROLL_SHADOW_BLUR,
            shadow_opacity = BROLL_SHADOW_OPACITY,
        )
        ch, cw = card_arr.shape[:2]

        # ARCHITECTURE_MASTER_V29: BROLL_CARD_CENTER_Y_RATIO = 0.471
        cx_pos  = (self.W - cw) // 2
        cy_base = int(self.H * BROLL_CARD_CENTER_Y_RATIO)
        cy_pos  = cy_base - ch // 2

        engine = self.make_timeline_engine()
        engine.add(
            engine.make_spring_entry_object(
                image_array = card_arr,
                t_start     = t_appear,
                t_end       = t_appear + duration,
                x           = cx_pos,
                y           = cy_pos,
                spring      = sp,
                slide_px    = SPRING_SLIDE_PX,
                z_index     = 10,
                tag         = "broll_card",
            )
        )

        base    = np.full((self.H, self.W, 3), 255, dtype=np.uint8)
        zoom_fx = EffectContinuousZoom(duration, GLOBAL_ZOOM_START, GLOBAL_ZOOM_END, "sine")

        def make_frame(t: float) -> np.ndarray:
            f = engine.render_frame(t, base.copy())
            return zoom_fx.apply(f, t - t_appear)

        return VideoClip(make_frame, duration=duration).set_fps(30)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Transitions
    # ══════════════════════════════════════════════════════════════════════

    def create_slide_transition(
        self,
        clip_out,
        clip_in,
        transition_duration: float = 0.30,
        direction:           str   = "left",
        spring:              bool  = True,
    ):
        td      = transition_duration
        vectors = {"left":(-self.W,0),"right":(self.W,0),"up":(0,-self.H),"down":(0,self.H)}
        dx, dy  = vectors.get(direction, (-self.W, 0))
        ease_in = self._ease_out_back if spring else self._ease_out_cubic

        out_clip = clip_out.set_duration(td).set_position(
            lambda t: (int(dx*self._ease_out_cubic(min(t/td,1.0))),
                       int(dy*self._ease_out_cubic(min(t/td,1.0))))
        )
        in_clip = clip_in.set_duration(td).set_position(
            lambda t: (int(-dx*(1.0-ease_in(min(t/td,1.0)))),
                       int(-dy*(1.0-ease_in(min(t/td,1.0)))))
        )
        return CompositeVideoClip([out_clip, in_clip], size=(self.W, self.H)).set_duration(td)

    def create_fade_transition(self, clip_out, clip_in, transition_duration=0.10):
        td = transition_duration
        def fo(gf, t):
            a = 1.0 - EasingLibrary.ease_in_out_sine(min(t/td, 1.0))
            return (gf(t).astype(np.float32) * a).astype(np.uint8)
        def fi(gf, t):
            a = EasingLibrary.ease_in_out_sine(min(t/td, 1.0))
            return (gf(t).astype(np.float32) * a).astype(np.uint8)
        return CompositeVideoClip(
            [clip_out.set_duration(td).fl(fo), clip_in.set_duration(td).fl(fi)],
            size=(self.W, self.H),
        ).set_duration(td)

    def should_slide_transition(self, prev_kw, curr_kw):
        return self._determine_mood(prev_kw) != self._determine_mood(curr_kw)

    def should_fade_transition(self, prev_kw, curr_kw):
        return not self.should_slide_transition(prev_kw, curr_kw)

    def get_slide_direction(self, scene_index):
        return ["left", "up", "left", "down"][scene_index % 4]

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 5 — Zoom
    # ══════════════════════════════════════════════════════════════════════

    def apply_global_slowzoom(self, clip, start_scale=1.0, end_scale=1.03):
        duration = clip.duration
        eff      = EffectContinuousZoom(duration, start_scale, end_scale, "sine")
        return clip.fl(lambda gf, t: eff.apply(gf(t), t))

    def apply_micro_zoom_continuous(self, clip, intensity=0.008):
        duration = clip.duration
        eff      = EffectContinuousZoom(duration, 1.0, 1.0 + intensity, "sine")
        return clip.fl(lambda gf, t: eff.apply(gf(t), t))

    def apply_motion_blur(self, clip, strength=0.35):
        fps = clip.fps or 30.0
        def blur(gf, t):
            cur = gf(t).astype(np.float32)
            if t == 0: return cur.astype(np.uint8)
            try:
                res = cur*(1.0-strength) + gf(max(0,t-1.0/fps)).astype(np.float32)*strength
            except:
                return cur.astype(np.uint8)
            return np.clip(res, 0, 255).astype(np.uint8)
        return clip.fl(blur)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 6 — Timeline Engine
    # ══════════════════════════════════════════════════════════════════════

    def make_timeline_engine(self) -> TimelineEngine:
        return TimelineEngine(width=self.W, height=self.H)

    def apply_effect_chain(self, clip, effects: List[EffectBase]):
        def chained(gf, t):
            frame = gf(t)
            for eff in effects:
                frame = eff.apply(frame, t)
            return frame
        return clip.fl(chained)

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 7 — Utilitaires
    # ══════════════════════════════════════════════════════════════════════

    def _apply_visual_mutation(self, image_path: str) -> str:
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                if random.random() > 0.5: img = ImageOps.mirror(img)
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

    def create_underline_draw_frame(
        self, frame, progress, y_pos, x_start, x_end,
        color=(123,44,191), thickness=6,
    ):
        img   = Image.fromarray(frame)
        draw  = ImageDraw.Draw(img)
        eased = EasingLibrary.ease_out_expo(max(0.0, min(1.0, progress)))
        x_cur = int(x_start + (x_end-x_start) * eased)
        if x_cur > x_start:
            draw.line([(x_start,y_pos),(x_cur,y_pos)], fill=color, width=thickness)
            draw.line([(x_start,y_pos+3),(x_cur,y_pos+3)], fill=color+(80,), width=max(1,thickness//3))
        return np.array(img)