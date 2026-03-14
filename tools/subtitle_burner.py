# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/subtitle_burner.py
"""
NEXUS SUBTITLE BURNER V17 — PREMIUM HORMOZI/ALI ABDAAL STYLE
═══════════════════════════════════════════════════════════════════════════════

IMPLÉMENTATION DU PLAN DA (Premium 9/10) - POLISH V17 :
  1. Typographie Massive & Ombre Portée : Casse originale, Font la plus grasse,
     Drop shadow adouci (Opacité 8%, Y-Offset 8px, Flou 25px).
  2. Pacing Karaoké : Clear Screen strict à 4 mots max, ou ponctuation (, . ! ?).
  3. Animation Pop : Interpolation mathématique absolue (Scale overshoot),
     0 à 115% en 0.08s (avec opacité), puis 100% à 0.20s.
  4. Pre-roll Temporel : Offset de -0.08s pour anticiper l'audio.
═══════════════════════════════════════════════════════════════════════════════
"""
import os
import random
import re
import math
import warnings
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

warnings.filterwarnings("ignore")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from moviepy.editor import VideoClip, CompositeVideoClip, ImageClip, TextClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("⚠️  moviepy manquant")


# ─────────────────────────────────────────────────────────────────────────────
# PALETTE PREMIUM (V17 - HORMOZI STYLE)
# ─────────────────────────────────────────────────────────────────────────────

BG_RGB       = (248, 249, 250)   # #F8F9FA - Blanc cassé (Neutre)
# POLISH V17: Remplacement du gris foncé par un Noir profond (#111111)
TEXT_RGB     = (17,   17,  17 )  # #111111 - Noir profond (Texte principal)
TEXT_DIM_RGB = (100, 100, 100)   # Gris moyen (Mots de liaison)
ACCENT_RGB   = (0,   210, 106)   # #00D26A - Vert (Succès, Argent)
MUTED_RGB    = (255, 59,  48 )   # #FF3B30 - Rouge (Alerte, Perte)


# ─────────────────────────────────────────────────────────────────────────────
# EASING — ARSENAL COMPLET
# ─────────────────────────────────────────────────────────────────────────────

def ease_out_expo(p: float) -> float:
    p = max(0.0, min(1.0, p))
    if p >= 1.0: return 1.0
    return 1.0 - pow(2.0, -10.0 * p)

def ease_in_expo(p: float) -> float:
    p = max(0.0, min(1.0, p))
    if p <= 0.0: return 0.0
    return pow(2.0, 10.0 * (p - 1.0))

def ease_in_out_sine(p: float) -> float:
    return -(math.cos(math.pi * max(0.0, min(1.0, p))) - 1) / 2


# ─────────────────────────────────────────────────────────────────────────────
# RENDU PIL : TEXTE → NUMPY ARRAY RGBA
# ─────────────────────────────────────────────────────────────────────────────

def _find_font(bold: bool = True, size: int = 100) -> ImageFont.FreeTypeFont:
    candidates = [
        "Montserrat-Black.ttf", "Montserrat-ExtraBold.ttf",
        "TheBoldFont.ttf", "Inter-Black.ttf", "Poppins-Black.ttf",
        "Arial-Black.ttf", "arialbd.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",    
        "C:\\Windows\\Fonts\\impact.ttf",     
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ] if bold else [
        "Montserrat-Bold.ttf", "Inter-Bold.ttf", "Poppins-Bold.ttf", "arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf"
    ]
    
    for fp in candidates:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, size)
                return font
            except Exception:
                continue
                
    print("\n" + "❌"*25)
    print("❌ [ERREUR CRITIQUE] FONT NON TROUVÉE !")
    print(f"❌ Impossible de charger une police premium. Taille demandée : {size}")
    print("❌ PIL force l'utilisation de 'load_default()' : une police minuscule bloquée à ~10px.")
    print("❌"*25 + "\n")
    
    return ImageFont.load_default()


def render_text_to_rgba(
    text:    str,
    fs:      int,
    bold:    bool  = True,
    color:   tuple = TEXT_RGB,
    max_w:   int   = 880,
) -> np.ndarray:
    
    # POLISH V17: Suppression du .upper() obligatoire, on garde la casse originale (ou capitalize si on veut)
    # text = text.upper() 
    
    print(f"🎨 [V17] Génération objet texte: '{text}' | font_size={fs} | color={color} | bold={bold}")
    
    font  = _find_font(bold=True, size=fs)
    
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    bbox  = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if tw > max_w:
        fs    = max(18, int(fs * (max_w / max(1, tw))))
        font  = _find_font(bold=True, size=fs)
        bbox  = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # POLISH V17: Padding agrandi pour absorber le Blur Radius très large (25px)
    pad_x, pad_y = 50, 50
    cw, ch = tw + pad_x * 2, th + pad_y * 2
    
    # Calque 1 : L'Ombre
    shadow_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d_shadow   = ImageDraw.Draw(shadow_img)
    
    # POLISH V17: Ombre portée UI Design -> Opacity 8% (~20), Y_Offset +8
    d_shadow.text((pad_x - bbox[0], pad_y - bbox[1] + 8), text, font=font, fill=(0, 0, 0, 20))
    
    # POLISH V17: Blur Radius poussé à 25
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=25))
    
    # Calque 2 : Le Texte Pur
    text_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d_text   = ImageDraw.Draw(text_img)
    d_text.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=color + (255,))
    
    # Composition Finale
    final_img = Image.alpha_composite(shadow_img, text_img)
    return np.array(final_img)


def render_price_badge_rgba(
    text:  str,
    fs:    int  = 180,
    max_w: int  = 880,
    style: str  = "dark_pill"
) -> np.ndarray:
    
    # POLISH V17: Suppression de la majuscule forcée
    # text = text.upper()
    
    font  = _find_font(bold=True, size=fs)
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    bbox  = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    ph, pv = 64, 40

    if (tw + ph * 2) > max_w:
        target_tw = max_w - (ph * 2)
        fs = max(18, int(fs * (target_tw / max(1, tw))))
        font  = _find_font(bold=True, size=fs)
        bbox  = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    cw = tw + ph * 2
    ch = th + pv * 2
    
    # POLISH V17: Espace d'ombre agrandi pour supporter le gros Blur
    sh = 40 

    rr = ch // 2

    canvas = Image.new("RGBA", (cw + sh * 2, ch + sh * 2), (0, 0, 0, 0))
    d      = ImageDraw.Draw(canvas)

    # POLISH V17: Ombre portée UI Design -> Opacity 8% (~20), Y_Offset +8
    d.rounded_rectangle([sh, sh + 8, cw + sh, ch + sh + 8], radius=rr, fill=(0, 0, 0, 20))
    
    # POLISH V17: Blur Radius poussé à 25
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=25))
    d      = ImageDraw.Draw(canvas)

    if style == "light_pill":
        d.rounded_rectangle([sh, sh, cw + sh, ch + sh], radius=rr, fill=(255, 255, 255, 255))
        tx, ty = sh + (cw - tw) // 2, sh + pv
        d.text((tx - bbox[0], ty - bbox[1]), text, font=font, fill=TEXT_RGB + (255,))
    else:
        d.rounded_rectangle([sh, sh, cw + sh, ch + sh], radius=rr, fill=TEXT_RGB + (255,))
        tx, ty = sh + (cw - tw) // 2, sh + pv
        d.text((tx - bbox[0], ty - bbox[1]), text, font=font, fill=(255, 255, 255, 255))

    return np.array(canvas)


# ─────────────────────────────────────────────────────────────────────────────
# MOTEUR DE COMPOSITION FRAME PAR FRAME
# ─────────────────────────────────────────────────────────────────────────────

class WordClip:
    __slots__ = (
        "arr", "w", "h",
        "target_x", "target_y",
        "t_start", "t_entry_end",
        "t_exit_start", "t_full_end",
        "anim_in",        
        "anim_out",       
        "ghost_opacity",
        "slide_px_in", "slide_px_out",
        "entry_dur", "exit_dur",
    )

    def __init__(
        self,
        arr:           np.ndarray,
        target_x:      int,
        target_y:      int,
        t_start:       float,
        t_entry_end:   float,
        t_exit_start:  float,
        t_full_end:    float,
        anim_in:       str   = "pop_overshoot",
        anim_out:      str   = "hard_swipe_up",
        ghost_opacity: float = 0.20,
        slide_px_in:   int   = 80,
        slide_px_out:  int   = 600,
    ):
        self.arr          = arr
        self.h, self.w    = arr.shape[:2]
        self.target_x     = target_x
        self.target_y     = target_y
        self.t_start      = t_start
        self.t_entry_end  = t_entry_end
        self.t_exit_start = t_exit_start
        self.t_full_end   = t_full_end
        self.anim_in      = anim_in
        self.anim_out     = anim_out
        self.ghost_opacity = ghost_opacity
        self.slide_px_in  = slide_px_in
        self.slide_px_out = slide_px_out
        self.entry_dur    = t_entry_end  - t_start
        self.exit_dur     = t_full_end   - t_exit_start


def _compose_frame(
    t:          float,
    clips:      List[WordClip],
    vid_w:      int,
    vid_h:      int,
    base_frame: np.ndarray,
) -> np.ndarray:
    
    frame = np.copy(base_frame)

    for c in clips:
        if t < c.t_start or t > c.t_full_end:
            continue

        elapsed = t - c.t_start
        
        # POLISH V17: Mathématiques de l'Animation (L'Overshoot Exact)
        if elapsed <= 0.0:
            scale = 0.01
            alpha_in = 0.0
        elif elapsed < 0.08:
            # T=0.00s à T=0.08s : Scale 0% -> 115%, Opacity 0% -> 100%
            p = elapsed / 0.08
            scale = max(0.01, 1.15 * p)
            alpha_in = p
        elif elapsed < 0.20:
            # T=0.08s à T=0.20s : Scale 115% -> 100% (Stabilisation), Opacity 100%
            p = (elapsed - 0.08) / 0.12
            scale = 1.15 - (0.15 * p)
            alpha_in = 1.0
        else:
            # Fin de l'entrée
            scale = 1.0
            alpha_in = 1.0

        if scale < 0.02 and alpha_in < 0.02:
            continue

        y_pos    = c.target_y
        x_pos    = c.target_x
        alpha    = min(1.0, alpha_in)

        # Animations de sortie
        if t >= c.t_exit_start:
            exit_p = min((t - c.t_exit_start) / max(c.exit_dur, 1e-6), 1.0)

            if c.anim_out == "hard_swipe_up":
                exit_ease = ease_in_expo(exit_p) 
                y_pos    -= int(c.slide_px_out * exit_ease)
                alpha     = alpha * (1.0 - exit_ease**2) 
            elif c.anim_out == "ghost_up":
                exit_ease = ease_out_expo(exit_p)
                y_pos    -= int(c.slide_px_out * exit_ease)
                alpha     = alpha * (1.0 - (1.0 - c.ghost_opacity) * exit_ease)
            elif c.anim_out == "fade_out":
                exit_ease = ease_out_expo(exit_p)
                alpha     = alpha * (1.0 - exit_ease)

        if alpha < 0.005:
            continue

        arr = c.arr
        h   = c.h
        w   = c.w

        if abs(scale - 1.0) > 0.003:
            nh  = max(1, int(h * scale))
            nw  = max(1, int(w * scale))
            img = Image.fromarray(arr).resize((nw, nh), Image.LANCZOS)
            arr = np.array(img)
            h, w = nh, nw
            y_pos += (c.h - h) // 2
            x_pos += (c.w - w) // 2

        y0s = max(0, -y_pos);         y0d = max(0, y_pos)
        x0s = max(0, -x_pos);         x0d = max(0, x_pos)
        y1s = min(h, vid_h - y_pos);  y1d = min(vid_h, y_pos + h)
        x1s = min(w, vid_w - x_pos);  x1d = min(vid_w, x_pos + w)

        if y1s <= y0s or x1s <= x0s:
            continue

        patch = arr[y0s:y1s, x0s:x1s]
        bg_sl = frame[y0d:y1d, x0d:x1d].astype(np.float32)

        if patch.shape[2] == 4:
            fg_a  = patch[:, :, 3:4].astype(np.float32) / 255.0 * alpha
            fg_rgb = patch[:, :, :3].astype(np.float32)
        else:
            fg_a   = np.full(patch.shape[:2] + (1,), alpha, dtype=np.float32)
            fg_rgb = patch.astype(np.float32)

        blended = bg_sl * (1.0 - fg_a) + fg_rgb * fg_a
        frame[y0d:y1d, x0d:x1d] = blended.clip(0, 255).astype(np.uint8)

    return frame


# ─────────────────────────────────────────────────────────────────────────────
# GROUPEUR DE TABLEAUX
# ─────────────────────────────────────────────────────────────────────────────

def group_into_tableaux(
    timeline:          List[Tuple[float, float, str]],
    # POLISH V17: Logique de Nettoyage -> Limite stricte à 4 mots à l'écran
    max_per_tableau:   int = 4, 
) -> List[List[Tuple[float, float, str]]]:
    tableaux, current = [], []

    def flush():
        nonlocal current
        if current:
            tableaux.append(current)
        current = []

    for entry in timeline:
        start, end, text = entry
        clean = text.strip()

        if "[PAUSE]" in clean.upper() or clean in ("…", "..."):
            flush()
            tableaux.append([(start, end, "[PAUSE]")])
            continue

        # POLISH V17: Force le clear screen dès qu'on a atteint la limite de 4 mots
        if len(current) >= max_per_tableau:
            flush()

        current.append(entry)

        # POLISH V17: Logique de Nettoyage (Clearing) -> Dès qu'il y a un point, ou une virgule.
        if clean and clean[-1] in ".!?,":
            flush()

    flush()
    return [t for t in tableaux if t]


# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class SubtitleBurner:

    VID_W = 1080
    VID_H = 1920
    SAFE_W = 880              
    CY     = 1920 // 2        

    FS_IMPACT = 280           
    FS_NORMAL = 200           
    FS_STOP   = 140           
    FS_BADGE  = 180           

    GAP          = 45           
    ENTRY_DUR    = 0.20         # POLISH V17: Temps total d'entrée stabilisé à 0.20s
    STAGGER      = 0.08         
    EXIT_DUR     = 0.16         
    GHOST_OP     = 0.20         
    BREATH_GAP   = 0.20         
    SLIDE_IN_PX  = 80           
    SLIDE_OUT_PX = 600          

    STOP_WORDS = {
        "le","la","les","un","une","des","ce","ces","de","du","à","au",
        "et","en","ne","se","sa","son","ses","on","y","il","elle","ils",
        "elles","je","tu","nous","vous","qui","que","quoi","dont","où",
        "si","or","ni","car","mais","ou","donc","par","sur","sous","avec",
        "pour","dans","vers","chez","c'est","the","a","an","in","on","at",
        "to","for","of","and","is","it","be","as","by","we","he","they","you"
    }
    
    KEYWORDS_ACCENT = {
        "argent", "succès", "secret", "outil", "profit", "gain", "winner", 
        "croissance", "million", "stratégie", "champion"
    }
    KEYWORDS_MUTED = {
        "perdre", "perte", "crash", "danger", "scam", "arnaque", "échec",
        "chute", "stop", "alerte", "attention", "faillite"
    }

    SFX_MAP = {
        "ACTION":  "click",
        "ACCENT":  "click",
        "BADGE":   "click_deep",
        "MUTED":   "swoosh",
        "STOP":    None,      
        "PAUSE":   None,
    }

    def __init__(
        self,
        model_size:   str = "base",
        platform:     str = "shorts",
        font:         str = "Montserrat-Black",     
        font_regular: str = "Montserrat-ExtraBold",    
        fontsize:     int = None,
    ):
        self.available    = WHISPER_AVAILABLE
        self.model        = None
        self.model_size   = model_size
        self.platform     = platform
        self.font         = font
        self.font_regular = font_regular
        self.fontsize     = fontsize or self.FS_NORMAL

        safe_v = {"shorts": 420, "tiktok": 520, "reels": 320}.get(platform, 420)
        mh     = int(1080 * 0.15)

        self.ass_header = f"""[Script Info]
Title: Nexus V17 Hormozi Typography
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TekiyoBold,{font},{self.FS_NORMAL},&H00111111&,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,4,0,1,0,1,2,{mh},{mh},{safe_v},1
Style: TekiyoRegular,{font_regular},{self.FS_STOP},&H004D4A4A&,&H000000FF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,3,0,1,0,0,2,{mh},{mh},{safe_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    @staticmethod
    def strip_tags(text: str) -> str:
        return re.sub(r'\[(BOLD|LIGHT|BADGE|PAUSE)\]', '', text).strip()

    def _is_stop(self, text: str) -> bool:
        words = text.lower().strip(".,!?:;'\"").split()
        return bool(words) and all(w.strip(".,!?") in self.STOP_WORDS for w in words)

    def get_semantic_class(self, text: str) -> str:
        clean = self.strip_tags(text).strip()
        if not clean or "[PAUSE]" in text.upper():
            return "PAUSE"
        if "[BADGE]" in text or re.search(r'\d+[\$€%]|[\$€]\d+|\d{2,}', clean):
            return "BADGE"
        if "[BOLD]" in text:
            return "ACTION"
        if "[LIGHT]" in text:
            return "STOP"
        low = clean.lower()
        if any(k in low for k in self.KEYWORDS_ACCENT):
            return "ACCENT"
        if any(k in low for k in self.KEYWORDS_MUTED):
            return "MUTED"
        if self._is_stop(clean):
            return "STOP"
        return "ACTION"

    def get_sfx_type(self, text: str) -> Optional[str]:
        return self.SFX_MAP.get(self.get_semantic_class(text))

    def _seconds_to_ass(self, s: float) -> str:
        h  = int(s // 3600)
        m  = int((s % 3600) // 60)
        sc = int(s % 60)
        cs = int((s - int(s)) * 100)
        return f"{h}:{m:02d}:{sc:02d}.{cs:02d}"

    def _build_tableau(
        self,
        entries:          List[Tuple[float, float, str]],
        next_tab_start:   Optional[float],
        is_conclusion:    bool,
    ) -> List[WordClip]:
        if not entries:
            return []

        n = len(entries)
        arrays = []
        anim_ins = []

        for idx, (start, end, text) in enumerate(entries):
            clean = self.strip_tags(text)
            sem   = self.get_semantic_class(text)

            is_badge = (sem == "BADGE" or bool(re.search(r'\d+[\$€%]|[\$€]\d+', clean)))

            if sem == "STOP":
                fs      = self.FS_STOP
                color   = TEXT_DIM_RGB
            elif sem in ["ACCENT", "MUTED", "ACTION"] or is_badge:
                fs      = self.FS_IMPACT
                color   = ACCENT_RGB if sem == "ACCENT" else (MUTED_RGB if sem == "MUTED" else TEXT_RGB)
            else:
                fs      = self.FS_NORMAL
                color   = TEXT_RGB

            bold    = True 
            anim_in = "pop_overshoot" 
            anim_ins.append(anim_in)

            if is_badge:
                style = "dark_pill" if random.random() > 0.5 else "light_pill"
                arr = render_price_badge_rgba(clean, fs=self.FS_BADGE, max_w=self.SAFE_W, style=style)
            else:
                arr = render_text_to_rgba(clean, fs, bold=bold, color=color, max_w=self.SAFE_W)

            arrays.append(arr)

        heights    = [a.shape[0] for a in arrays]
        widths     = [a.shape[1] for a in arrays]
        total_h    = sum(heights) + self.GAP * (n - 1)
        stack_y    = self.CY - total_h // 2

        word_clips = []
        for idx, (arr, (start, end, text)) in enumerate(zip(arrays, entries)):
            h, w = arr.shape[:2]
            x    = (self.VID_W - w) // 2
            y    = stack_y

            stack_y += h + self.GAP

            # POLISH V17: L'Offset Temporel (Pre-roll). Anticipation absolue de -0.08s
            t_start     = max(0.0, (start - 0.08) + (idx * self.STAGGER))
            t_entry_end = t_start + self.ENTRY_DUR

            if next_tab_start is not None:
                t_exit_start = next_tab_start - self.EXIT_DUR * 0.5
                t_full_end   = next_tab_start + self.ENTRY_DUR
                anim_out     = "hard_swipe_up"
            else:
                t_exit_start = end - self.EXIT_DUR
                t_full_end   = end + 0.1
                anim_out     = "fade_out"

            anim_in = "pop_overshoot"

            word_clips.append(WordClip(
                arr           = arr,
                target_x      = x,
                target_y      = y,
                t_start       = t_start,
                t_entry_end   = t_entry_end,
                t_exit_start  = t_exit_start,
                t_full_end    = t_full_end,
                anim_in       = anim_in,
                anim_out      = anim_out,
                ghost_opacity = self.GHOST_OP,
                slide_px_in   = self.SLIDE_IN_PX,
                slide_px_out  = self.SLIDE_OUT_PX,
            ))

        return word_clips

    def burn_subtitles(
        self,
        video_clip,
        timeline: List[Tuple[float, float, str]],
    ):
        if not MOVIEPY_AVAILABLE:
            return video_clip

        if not timeline or len(timeline) == 0:
            print("⚠️  [SubtitleBurner] Alerte: La timeline des sous-titres est vide. Rendu de la vidéo originale sans incrustation.")
            return video_clip

        print(f"🎬  Massive Typography V17 (Premium DA) — {len(timeline)} scènes…")

        # POLISH V17: Mise à jour de l'appel à 4 mots max
        tableaux = group_into_tableaux(timeline, max_per_tableau=4)
        all_clips: List[WordClip] = []

        for i, tab in enumerate(tableaux):
            if len(tab) == 1 and "[PAUSE]" in tab[0][2].upper():
                continue

            next_start = None
            for future in tableaux[i + 1:]:
                if not (len(future) == 1 and "[PAUSE]" in future[0][2].upper()):
                    next_start = future[0][0]
                    break

            is_conclusion = (i > 0 and tab[-1][2].strip().endswith((".", "!", "?")))
            clips = self._build_tableau(tab, next_start, is_conclusion)
            all_clips.extend(clips)

        vid_w    = video_clip.w
        vid_h    = video_clip.h
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        last_valid_frame = None

        def make_frame(t):
            nonlocal last_valid_frame
            try:
                base_frame = video_clip.get_frame(t)
                last_valid_frame = base_frame
            except Exception as e:
                if last_valid_frame is not None:
                    base_frame = last_valid_frame
                else:
                    base_frame = np.zeros((vid_h, vid_w, 3), dtype=np.uint8)
                    
            return _compose_frame(t, all_clips, vid_w, vid_h, base_frame=base_frame)

        from moviepy.editor import VideoClip as MpVideoClip
        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)

        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    def _load_model(self):
        if not self.model and self.available:
            print(f"⏳  Whisper '{self.model_size}'…")
            self.model = whisper.load_model(self.model_size)

    def _fin_chunk(self, chunks, wl):
        if wl:
            chunks.append({
                "start": wl[0]["start"],
                "end":   wl[-1]["end"],
                "text":  " ".join(w["word"] for w in wl).strip()
            })

    def _split_into_chunks(self, words: list) -> list:
        chunks, cur = [], []
        for wo in words:
            clean = wo["word"].replace("\\", "").replace("\n", " ").strip()
            if not clean:
                continue
            cur.append({"word": clean, "start": wo["start"], "end": wo["end"]})
            # POLISH V17: Ajout de la virgule pour split logiquement
            has_punct  = clean[-1] in ".?!:," if clean else False
            chunk_full = len(cur) >= 2
            if (not self._is_stop(clean)) or has_punct or chunk_full:
                self._fin_chunk(chunks, cur)
                cur = []
        if cur:
            self._fin_chunk(chunks, cur)
        return self._sanitize(chunks)

    def _sanitize(self, chunks):
        out, i = [], 0
        while i < len(chunks):
            c = chunks[i].copy()
            if c["end"] - c["start"] < 0.08 and i < len(chunks) - 1:
                nxt       = chunks[i + 1]
                c["text"] = f"{c['text']} {nxt['text']}"
                c["end"]  = nxt["end"]
                out.append(c)
                i += 2
            else:
                out.append(c)
                i += 1
        return out

    def generate_ass_file(self, audio_path: Path, output_ass: Path) -> bool:
        if not self.available:
            return False
        self._load_model()
        try:
            result    = self.model.transcribe(str(audio_path), word_timestamps=True)
            all_words = [w for seg in result["segments"] for w in seg.get("words", [])]
            chunks    = self._split_into_chunks(all_words)
            with open(output_ass, "w", encoding="utf-8") as f:
                f.write(self.ass_header)
                for c in chunks:
                    st  = self._seconds_to_ass(c["start"])
                    en  = self._seconds_to_ass(c["end"])
                    # POLISH V17: Retrait de .upper() dans l'ASS
                    txt = c["text"].replace("\\", "")
                    sem = self.get_semantic_class(txt)
                    sty = "TekiyoBold" if sem in ("ACTION", "ACCENT") else "TekiyoRegular"
                    
                    # POLISH V17: ASS tag mis à jour avec la logique V17
                    pop = r"{\fscx1\fscy1\alpha&HFF&\t(0,80,\fscx115\fscy115\alpha&H00&)\t(80,200,\fscx100\fscy100)}"
                    
                    f.write(f"Dialogue: 0,{st},{en},{sty},,0,0,0,,{pop}{txt}\n")
            return True
        except Exception as e:
            print(f"❌  Whisper error: {e}")
            return False