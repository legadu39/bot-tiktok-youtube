# -*- coding: utf-8 -*-
import os
import random
import tempfile
from typing import List, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoClip
    MOVIEPY_OK = True
except ImportError:
    MOVIEPY_OK = False

# Imports relatifs depuis notre package refactorisé
from .easing import EasingLibrary
from .physics import SpringPhysics
from .effects import EffectBase, EffectContinuousZoom, EffectSpringOvershoot
from .timeline import TimelineObject, TimelineEngine
from .layout import SmartLayoutManager
from .context import SceneContext

class SceneAnimator:
    WHITE_BG_COLOR = (255, 255, 255)
    CREAM_BG_COLOR = (245, 245, 247)
    SHADOW_COLOR   = (200, 200, 205, 80)
    _ease = EasingLibrary

    def __init__(self, width: int = 1080, height: int = 1920):
        self.W        = width
        self.H        = height
        self.temp_dir = tempfile.gettempdir()
        self.layout = SmartLayoutManager(
            canvas_w=width, canvas_h=height, safe_left=80, safe_right=80, safe_top=200, safe_bottom=350
        )

    # ── Backward-compat easing aliases ──
    @staticmethod
    def _ease_out_cubic(p): return EasingLibrary.ease_out_cubic(p)
    @staticmethod
    def _ease_in_out_sine(p): return EasingLibrary.ease_in_out_sine(p)
    @staticmethod
    def _ease_in_expo(p): return EasingLibrary.ease_in_expo(p)
    @staticmethod
    def _ease_out_expo(p): return EasingLibrary.ease_out_expo(p)
    @staticmethod
    def _ease_out_back(p, overshoot=1.70158): return EasingLibrary.ease_out_back(p, overshoot)
    @staticmethod
    def _ease_in_out_spring(p): return EasingLibrary.ease_in_out_cubic(p)
    @staticmethod
    def _ease_out(p): return EasingLibrary.ease_out_cubic(p)

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
        if mood == "URGENT": return "ZOOM_IN_HARD" if context.consecutive_count < 3 else "ZOOM_IN"
        if context.last_motion in ["ZOOM_IN", "ZOOM_IN_HARD"]: return random.choice(["STATIC", "ZOOM_OUT"])
        if context.last_motion in ["STATIC", "ZOOM_OUT"]: return "ZOOM_IN"
        return "STATIC"

    def create_background(self, output_path: str, style: str = "white") -> str:
        color = self.WHITE_BG_COLOR if style == "white" else self.CREAM_BG_COLOR
        img   = Image.new("RGB", (self.W, self.H), color=color)
        img.save(output_path, quality=98)
        return output_path

    def create_cream_background(self, output_path: str) -> str:
        return self.create_background(output_path, style="cream")

    def create_dynamic_clip(self, image_path, duration: float = 5.0, context_keywords: str = "", scene_context: SceneContext = None, apply_mutation: bool = False):
        if not MOVIEPY_OK: raise ImportError("moviepy requis pour create_dynamic_clip")
        if scene_context is None: scene_context = SceneContext()

        working_path = self._apply_visual_mutation(str(image_path)) if apply_mutation else image_path
        if apply_mutation: duration += random.uniform(-0.1, 0.1)

        mood        = self._determine_mood(context_keywords)
        motion_type = self._decide_motion_strategy(mood, scene_context)
        scene_context.update(motion_type)

        tx, ty = self._get_interest_center(str(working_path))
        zoom_factors = {"ZOOM_IN_HARD": 1.05, "ZOOM_IN": 1.03, "ZOOM_OUT": 1.04, "STATIC": 1.00, "PAN_SLOW": 1.05}
        zoom_factor = zoom_factors.get(motion_type, 1.02)

        try:
            img = ImageClip(str(working_path)).set_duration(duration)
        except Exception:
            img = ImageClip(str(image_path)).set_duration(duration)

        img_w, img_h = img.size
        ratio_canvas, ratio_img = self.W / self.H, img_w / img_h
        new_h, new_w = self.H * zoom_factor, self.W * zoom_factor

        if ratio_img > ratio_canvas:
            final_h = new_h
            final_w = final_h * ratio_img
        else:
            final_w = new_w
            final_h = final_w / ratio_img

        img = img.resize(width=int(final_w)) if final_w > final_h * ratio_img else img.resize(height=int(final_h))
        xov, yov = img.w - self.W, img.h - self.H
        ideal_x, ideal_y = (self.W / 2) - (tx * img.w), (self.H / 2) - (ty * img.h)
        focus_x, focus_y = max(-xov, min(0, ideal_x)), max(-yov, min(0, ideal_y))
        cx, cy = -xov / 2, -yov / 2
        start_x, start_y, dest_x, dest_y = cx, cy, cx, cy

        if "ZOOM_IN" in motion_type: dest_x, dest_y = focus_x, focus_y
        elif motion_type == "ZOOM_OUT": start_x, start_y = focus_x, focus_y
        elif motion_type == "PAN_SLOW":
            if xov > yov:
                start_x, dest_x = (0 if focus_x < cx else -xov), (-xov if focus_x < cx else 0)
            else:
                start_y, dest_y = 0, -yov

        def position_func(t):
            if motion_type == "STATIC": return (int(cx), int(cy))
            p = t / duration
            p = (p**3 if motion_type == "ZOOM_IN_HARD" else p if motion_type == "PAN_SLOW" else -p * (p - 2))
            return (int(start_x + (dest_x - start_x) * p), int(start_y + (dest_y - start_y) * p))

        img = img.set_position(position_func)
        return CompositeVideoClip([img], size=(self.W, self.H))

    def create_scene(self, image_path, duration: float = 5.0, effect=None, resolution=None, apply_mutation: bool = False):
        return self.create_dynamic_clip(image_path, duration=duration, apply_mutation=apply_mutation)

    def apply_global_slowzoom(self, clip, start_scale=1.0, end_scale=1.05):
        duration = clip.duration
        effect   = EffectContinuousZoom(duration, start_scale, end_scale, "sine")
        return clip.fl(lambda get_frame, t: effect.apply(get_frame(t), t))

    def apply_micro_zoom_continuous(self, clip, intensity: float = 0.008):
        duration = clip.duration
        return clip.fl(lambda get_frame, t: EffectContinuousZoom(duration, 1.0, 1.0 + intensity).apply(get_frame(t), t))

    def create_slide_transition(self, clip_out, clip_in, transition_duration: float = 0.30, direction: str = "left", spring: bool = True):
        td = transition_duration
        vectors = {"left": (-self.W,0), "right":(self.W,0), "up":(0,-self.H), "down":(0,self.H)}
        dx, dy  = vectors.get(direction, (-self.W, 0))
        ease_in = self._ease_out_back if spring else self._ease_out_cubic

        out_clip = clip_out.set_duration(td).set_position(
            lambda t: (int(dx * self._ease_out_cubic(min(t/td, 1.0))), int(dy * self._ease_out_cubic(min(t/td, 1.0))))
        )
        in_clip = clip_in.set_duration(td).set_position(
            lambda t: (int(-dx * (1.0 - ease_in(min(t/td, 1.0)))), int(-dy * (1.0 - ease_in(min(t/td, 1.0)))))
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

    def apply_motion_blur(self, clip, strength=0.35, num_samples=2):
        fps = clip.fps or 30.0
        def blur(get_frame, t):
            cur = get_frame(t).astype(np.float32)
            if t == 0: return cur.astype(np.uint8)
            res = cur * (1.0 - strength)
            try:
                res += get_frame(max(0, t - 1.0/fps)).astype(np.float32) * strength
            except Exception:
                return cur.astype(np.uint8)
            return np.clip(res, 0, 255).astype(np.uint8)
        return clip.fl(blur)

    def create_underline_draw_frame(self, frame: np.ndarray, progress: float, y_pos: int, x_start: int, x_end: int, color: tuple = (123, 44, 191), thickness: int = 6) -> np.ndarray:
        img   = Image.fromarray(frame)
        draw  = ImageDraw.Draw(img)
        eased = EasingLibrary.ease_out_expo(max(0.0, min(1.0, progress)))
        x_cur = int(x_start + (x_end - x_start) * eased)
        if x_cur > x_start:
            draw.line([(x_start, y_pos), (x_cur, y_pos)], fill=color, width=thickness)
            shadow_c = color + (80,) if len(color) == 3 else color
            draw.line([(x_start, y_pos+3), (x_cur, y_pos+3)], fill=shadow_c, width=max(1, thickness//3))
        return np.array(img)

    def should_slide_transition(self, prev_kw: str, curr_kw: str) -> bool: return self._determine_mood(prev_kw) != self._determine_mood(curr_kw)
    def should_fade_transition(self, prev_kw: str, curr_kw: str) -> bool: return not self.should_slide_transition(prev_kw, curr_kw)
    def get_slide_direction(self, scene_index: int) -> str: return ["left", "up", "left", "down"][scene_index % 4]

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

    def create_ui_price_card(self, text: str, width: int = None, bg_color: tuple = (255, 255, 255), accent_color: tuple = (123, 44, 191), font_path: str = None) -> np.ndarray:
        if width is None: width = int(self.W * 0.55)
        pad_h, pad_v, radius, font_size = 48, 32, 32, 88
        candidates = [font_path, "Inter-ExtraBold.ttf", "Montserrat-ExtraBold.ttf", "Poppins-Bold.ttf", "arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        pil_font = None
        for fp in candidates:
            if fp and os.path.exists(str(fp)):
                try: pil_font = ImageFont.truetype(fp, font_size); break
                except Exception: continue
        if pil_font is None: pil_font = ImageFont.load_default()
        try:
            bbox = pil_font.getbbox(text)
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        except Exception:
            tw, th = len(text)*45, 60
        cw, ch, r = min(tw + pad_h*2, width), th + pad_v*2 + 8, min(radius, (th + pad_v*2 + 8)//2)
        canvas = Image.new("RGBA", (cw+12, ch+12), (0,0,0,0))
        draw   = ImageDraw.Draw(canvas)
        draw.rounded_rectangle([6,6,cw+5,ch+5], radius=r, fill=(180,180,185,120))
        draw.rounded_rectangle([-2,-2,cw-2,ch-2], radius=r, fill=(255,255,255,200))
        draw.rounded_rectangle([0,0,cw-1,ch-1], radius=r, fill=bg_color+(255,) if len(bg_color)==3 else bg_color)
        draw.text(((cw-tw)//2, pad_v), text, font=pil_font, fill=accent_color+(255,))
        return np.array(canvas)

    def create_repeater_matrix(self, element_path, cols=8, rows=14, output_path=None, opacity=0.12, bg_color=(255,255,255), canvas_w=None, canvas_h=None) -> str:
        if output_path is None: output_path = os.path.join(self.temp_dir, f"rep_{random.randint(10000,99999)}.png")
        cw, ch = canvas_w or self.W, canvas_h or self.H
        canvas  = Image.new("RGBA", (cw, ch), bg_color + (255,))
        cell_w, cell_h = cw//cols, ch//rows
        try: elem = Image.open(element_path).convert("RGBA")
        except Exception: elem = Image.new("RGBA", (20,20), (29,29,31,255))
        elem.thumbnail((int(cell_w*0.75), int(cell_h*0.75)), Image.LANCZOS)
        if opacity < 1.0:
            r, g, b, a = elem.split()
            a = a.point(lambda x: int(x * opacity))
            elem = Image.merge("RGBA", (r,g,b,a))
        for row in range(rows):
            for col in range(cols):
                ox = (cell_w//4) if row%2==1 else 0
                x, y = col*cell_w + (cell_w - elem.width)//2 + ox, row*cell_h + (cell_h - elem.height)//2
                canvas.paste(elem, (x, y), mask=elem.split()[3])
        canvas.convert("RGB").save(output_path, quality=95)
        return output_path

    def create_animated_repeater_clip(self, element_path, duration, cols=8, rows=14, opacity=0.12, bg_color=(255,255,255)):
        ow, oh = int(self.W * 1.3), int(self.H * 1.3)
        mp = self.create_repeater_matrix(element_path, int(cols*1.3), int(rows*1.3), opacity=opacity, bg_color=bg_color, canvas_w=ow, canvas_h=oh)
        clip = ImageClip(mp).set_duration(duration)
        xov, yov = ow - self.W, oh - self.H
        def pos(t):
            ease = EasingLibrary.ease_in_out_sine(t/max(duration,1e-6))
            return (int(-xov*0.8*ease), int(-yov*0.8*ease))
        return CompositeVideoClip([clip.set_position(pos)], size=(self.W, self.H))

    def make_timeline_engine(self) -> TimelineEngine:
        return TimelineEngine(width=self.W, height=self.H)

    def create_image_card_clip(self, image_path: str, duration: float, card_w: int = None, corner_radius: int = 37, shadow_blur: int = 24, t_appear: float = 0.0, spring: SpringPhysics = None):
        if not MOVIEPY_OK: raise ImportError("moviepy requis")
        cw = card_w or int(self.W * 0.52)
        sp = spring or SpringPhysics.reference_pop()
        sp_eff = EffectSpringOvershoot(spring=sp, slide_px=20)

        try: img_pil = Image.open(image_path).convert("RGBA")
        except Exception: img_pil = Image.new("RGBA", (cw, cw), (30, 30, 30, 255))
        ch = int(img_pil.height * (cw / img_pil.width))
        img_pil = img_pil.resize((cw, ch), Image.LANCZOS)

        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw-1, ch-1], radius=corner_radius, fill=255)
        img_pil.putalpha(mask)

        shadow = Image.new("RGBA", (cw + 40, ch + 40), (0, 0, 0, 0))
        smask  = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(smask).rounded_rectangle([0,0,cw-1,ch-1], radius=corner_radius, fill=180)
        shadow.paste(Image.new("RGBA", (cw, ch), (0, 0, 0, 90)), (20, 16), mask=smask)
        shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        shadow.paste(img_pil, (10, 10), mask=img_pil.split()[3])

        card_arr = np.array(shadow)
        card_h, card_w = card_arr.shape[:2]
        cx_pos, cy_pos = (self.W - card_w) // 2, (self.H - card_h) // 2

        engine = self.make_timeline_engine()
        engine.add(TimelineObject(
            t_start=t_appear, t_end=t_appear + duration,
            render_fn=lambda t: card_arr,
            pos_fn=lambda t: (cx_pos, cy_pos + sp_eff.state_at(t - t_appear)["y_offset"]) if t >= t_appear else (cx_pos, self.H + 50),
            alpha_fn=lambda t: sp_eff.state_at(t - t_appear)["alpha"] if t >= t_appear else 0.0,
            z_index=10, tag="image_card"
        ))

        base = np.full((self.H, self.W, 3), 255, dtype=np.uint8)
        zoom_fx = EffectContinuousZoom(duration=duration, scale_start=1.0, scale_end=1.03)
        return VideoClip(lambda t: zoom_fx.apply(engine.render_frame(t, base.copy()), t), duration=duration).set_fps(30)

    def create_price_comparison_clip(self, prices: List[Tuple[str, Tuple[int,int,int]]], duration: float, block_size: int = 140, t_appear: float = 0.0):
        if not MOVIEPY_OK: raise ImportError("moviepy requis")
        n, STAGGER, cy = len(prices), 0.08, self.H // 2
        offsets_y = [0, -30, 30, -20, 20][:n]
        gap_x = block_size + 60
        start_x = (self.W - ((n - 1) * gap_x)) // 2

        def render_block(label: str, color: Tuple) -> np.ndarray:
            bs, pad_shadow = block_size, 20
            total = bs + pad_shadow * 2
            canvas = Image.new("RGBA", (total, total + 40), (0,0,0,0))
            smask = Image.new("L", (bs, bs), 0)
            ImageDraw.Draw(smask).rounded_rectangle([0,0,bs-1,bs-1], radius=24, fill=120)
            shadow_full= Image.new("RGBA", (total, total), (0,0,0,0))
            shadow_full.paste(Image.new("RGBA", (bs, bs), color + (80,)), (pad_shadow, pad_shadow), mask=smask)
            shadow_full = shadow_full.filter(ImageFilter.GaussianBlur(14))
            canvas.paste(shadow_full, (0, 4), mask=shadow_full.split()[3])

            block = Image.new("RGBA", (bs, bs), color + (255,))
            bmask = Image.new("L", (bs, bs), 0)
            ImageDraw.Draw(bmask).rounded_rectangle([0,0,bs-1,bs-1], radius=24, fill=255)
            block.putalpha(bmask)
            canvas.paste(block, (pad_shadow, pad_shadow), mask=block.split()[3])
            return np.array(canvas)

        def render_label(label: str, fs: int = 48) -> np.ndarray:
            font = ImageFont.load_default()
            for fp in ["Inter-Bold.ttf","Montserrat-Bold.ttf","DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                if os.path.exists(fp):
                    try: font = ImageFont.truetype(fp, fs); break
                    except Exception: pass
            try:
                bbox = ImageDraw.Draw(Image.new("RGBA",(1,1))).textbbox((0,0), label, font=font)
                tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            except Exception: tw, th = len(label)*28, 40
            canvas = Image.new("RGBA", (tw+20, th+10), (0,0,0,0))
            ImageDraw.Draw(canvas).text((10,5), label, font=font, fill=(30,30,30,255))
            return np.array(canvas)

        engine = self.make_timeline_engine()
        for i in range(n):
            t_birth = t_appear + i * STAGGER
            bx, by = start_x + i * gap_x, cy + offsets_y[i] - block_size // 2
            barr, larr = render_block(*prices[i]), render_label(prices[i][0])
            sp_eff = EffectSpringOvershoot(spring=SpringPhysics.reference_pop(), slide_px=25)
            lx, ly = bx + (block_size - larr.shape[1]) // 2, by - larr.shape[0] - 8

            # Binding tardif sécurisé pour les lambdas
            def make_render(arr): return lambda t: arr
            def make_alpha(tb, eff): return lambda t: 0.0 if t - tb < 0 else eff.state_at(t - tb)["alpha"]
            def make_pos(x_val, y_val, tb, eff): return lambda t: (x_val, y_val + 60) if t - tb < 0 else (x_val, y_val + eff.state_at(t - tb)["y_offset"])

            engine.add(TimelineObject(t_start=t_appear, t_end=t_appear+duration, render_fn=make_render(barr), pos_fn=make_pos(bx - 20, by, t_birth, sp_eff), alpha_fn=make_alpha(t_birth, sp_eff), z_index=10))
            engine.add(TimelineObject(t_start=t_appear, t_end=t_appear+duration, render_fn=make_render(larr), pos_fn=make_pos(lx, ly, t_birth, sp_eff), alpha_fn=make_alpha(t_birth, sp_eff), z_index=11))

        dash_arr = self._make_dash_line(self.W, 4)
        engine.add(TimelineObject(
            t_start=t_appear + (n-1)*STAGGER + 0.15, t_end=t_appear + duration,
            render_fn=lambda t: dash_arr, pos_fn=lambda t: (0, cy - 2),
            alpha_fn=lambda t: min(1.0, (t - (t_appear + (n-1)*STAGGER + 0.15)) / 0.2), z_index=5
        ))
        base = np.full((self.H, self.W, 3), 255, dtype=np.uint8)
        return VideoClip(lambda t: engine.render_frame(t, base.copy()), duration=duration).set_fps(30)

    def _make_dash_line(self, width: int, height: int = 4, dash: int = 20, gap: int = 12, color=(180,180,185)) -> np.ndarray:
        arr  = np.zeros((height, width, 4), dtype=np.uint8)
        x, draw_dash = 0, True
        while x < width:
            end = min(x + (dash if draw_dash else gap), width)
            if draw_dash: arr[:, x:end, :3], arr[:, x:end, 3] = color, 200
            x += (dash if draw_dash else gap)
            draw_dash = not draw_dash
        return arr

    def apply_effect_chain(self, clip, effects: List[EffectBase]):
        def chained(get_frame, t):
            frame = get_frame(t)
            for eff in effects: frame = eff.apply(frame, t)
            return frame
        return clip.fl(chained)