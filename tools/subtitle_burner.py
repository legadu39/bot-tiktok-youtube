# -*- coding: utf-8 -*-
### bot tiktok youtube/tools/subtitle_burner.py
"""
NEXUS SUBTITLE BURNER V15 — MASSIVE TYPOGRAPHY & SAFE ZONE
═══════════════════════════════════════════════════════════════════════════════

PHILOSOPHIE : Le Squint Test (Test des yeux plissés). Chaque mot d'impact doit 
être perçu comme un bloc noir massif au centre de l'écran.

IMPLÉMENTATION DU PLAN V15 (Scale & Proportion) :
  1. Auto-Scaling "Massive Clamp" : FS_IMPACT est poussé à 280. Les mots courts 
     prennent 1/3 de l'écran. Les mots longs sont bridés à 880px (80% de l'écran).
  2. Safe Zone Verticale : Les mots s'empilent uniquement dans le tiers central 
     grâce au calcul dynamique des hauteurs. Haut et bas restent vierges.
  3. Badges mis à jour : Le calcul de la largeur maximale (max_w) est maintenant
     aussi appliqué aux badges Pill Shape pour éviter qu'ils ne débordent.
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
from PIL import Image, ImageDraw, ImageFont

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
# PALETTE PREMIUM (V15 - DÉSATURÉE ET MINIMALISTE)
# ─────────────────────────────────────────────────────────────────────────────

BG_RGB       = (255, 255, 255)   # #FFFFFF - Blanc pur
TEXT_RGB     = (17,  17,  17 )   # #111111 - Noir riche, pas aveuglant
TEXT_DIM_RGB = (74,  74,  77 )   # #4A4A4D - Gris anthracite pour mots de liaison
ACCENT_RGB   = (123, 44,  191)   # #7B2CBF - Violet premium
MUTED_RGB    = (230, 57,  70 )   # #E63946 - Rouge corail / terre cuite désaturé


# ─────────────────────────────────────────────────────────────────────────────
# EASING — ARSENAL COMPLET
# ─────────────────────────────────────────────────────────────────────────────

def ease_out_expo(p: float) -> float:
    """Démarrage explosif + freinage chirurgicalement précis (règle des 80%)."""
    p = max(0.0, min(1.0, p))
    if p >= 1.0:
        return 1.0
    return 1.0 - pow(2.0, -10.0 * p)


def ease_in_expo(p: float) -> float:
    """Départ très lent, puis accélération fulgurante (pour les sorties Hard Wipe)."""
    p = max(0.0, min(1.0, p))
    if p <= 0.0:
        return 0.0
    return pow(2.0, 10.0 * (p - 1.0))


def ease_in_out_sine(p: float) -> float:
    """Sinusoïdale — pour les sorties douces."""
    return -(math.cos(math.pi * max(0.0, min(1.0, p))) - 1) / 2


def ease_out_back(p: float, overshoot: float = 1.2) -> float:
    """Micro-rebond élégant à l'arrivée (Overshoot)."""
    p  = max(0.0, min(1.0, p))
    c1 = overshoot
    return 1.0 + (c1 + 1.0) * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2


# ─────────────────────────────────────────────────────────────────────────────
# RENDU PIL : TEXTE → NUMPY ARRAY RGBA
# ─────────────────────────────────────────────────────────────────────────────

def _find_font(bold: bool = True, size: int = 100) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            "Inter-ExtraBold.ttf", "Inter_ExtraBold.ttf",
            "Inter-Black.ttf",     "Inter_Black.ttf",
            "Montserrat-ExtraBold.ttf", "Montserrat-Black.ttf",
            "Poppins-ExtraBold.ttf", "Poppins-Black.ttf",
            "arial.ttf", "Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold else
        [
            "Inter-Medium.ttf",  "Inter_Medium.ttf",
            "Inter-Regular.ttf", "Inter_Regular.ttf",
            "Montserrat-Medium.ttf",
            "Poppins-Medium.ttf",
            "arial.ttf", "Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_text_to_rgba(
    text:    str,
    fs:      int,
    bold:    bool  = True,
    color:   tuple = TEXT_RGB,
    max_w:   int   = 880,
) -> np.ndarray:
    """Rend du texte en array RGBA. V15: Clamp mathématique ultra-précis."""
    font  = _find_font(bold=bold, size=fs)
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    bbox  = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # V15 : Clamp exact à la limite de la Safe Zone (80% écran)
    if tw > max_w:
        fs    = max(18, int(fs * (max_w / max(1, tw))))
        font  = _find_font(bold=bold, size=fs)
        bbox  = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad = 10
    img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=color + (255,))
    return np.array(img)


def render_price_badge_rgba(
    text:  str,
    fs:    int  = 180,
    max_w: int  = 880,
    style: str  = "dark_pill"
) -> np.ndarray:
    """Badge Pill Shape Premium Apple. V15: Intègre l'Auto-Scaling pour éviter l'overflow."""
    font  = _find_font(bold=True, size=fs)
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    bbox  = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Paddings adaptés aux polices géantes V15
    ph, pv = 64, 40

    # V15 : Auto-Scaling appliqué au badge total (texte + padding)
    if (tw + ph * 2) > max_w:
        target_tw = max_w - (ph * 2)
        fs = max(18, int(fs * (target_tw / max(1, tw))))
        font  = _find_font(bold=True, size=fs)
        bbox  = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    cw = tw + ph * 2
    ch = th + pv * 2
    sh = 16 # Ombre adaptée à l'échelle massive

    # Pill Shape Mathématique
    rr = ch // 2

    canvas = Image.new("RGBA", (cw + sh + 4, ch + sh + 4), (0, 0, 0, 0))
    d      = ImageDraw.Draw(canvas)

    if style == "light_pill":
        # Ombre très douce et diffuse
        d.rounded_rectangle([sh//2, sh//2, cw + sh//2, ch + sh//2], radius=rr, fill=(0, 0, 0, 15))
        # Fond blanc
        d.rounded_rectangle([0,  0,  cw - 1,  ch - 1], radius=rr, fill=(255, 255, 255, 255))
        # Texte noir profond
        tx, ty = (cw - tw) // 2, pv
        d.text((tx - bbox[0], ty - bbox[1]), text, font=font, fill=TEXT_RGB + (255,))
    else:
        # Dark Pill (très premium)
        # Fond Noir
        d.rounded_rectangle([0,  0,  cw - 1,  ch - 1], radius=rr, fill=TEXT_RGB + (255,))
        # Texte Blanc pur
        tx, ty = (cw - tw) // 2, pv
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
        "anim_in",        # "slide_up" | "scale_fade" | "pop_overshoot" | "fade_in"
        "anim_out",       # "ghost_up" | "hard_swipe_up" | "fade_out"
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
        anim_in:       str   = "slide_up",
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
    t:       float,
    clips:   List[WordClip],
    vid_w:   int,
    vid_h:   int,
    bg:      tuple = BG_RGB,
) -> np.ndarray:
    frame = np.full((vid_h, vid_w, 3), bg, dtype=np.uint8)

    for c in clips:
        if t < c.t_start or t > c.t_full_end:
            continue

        entry_p   = min((t - c.t_start) / max(c.entry_dur, 1e-6), 1.0)
        
        # Animations d'entrée
        if c.anim_in == "pop_overshoot":
            alpha_in = min(entry_p * 3.0, 1.0) # Fade très rapide
            y_pos    = c.target_y
            # Overshoot mathématique : part de 0.5, monte à 1.15, revient à 1.0
            scale    = 0.5 + 0.5 * ease_out_back(entry_p, overshoot=1.8)
        elif c.anim_in == "fade_in":
            alpha_in = ease_out_expo(entry_p)
            y_pos    = c.target_y
            scale    = 1.0
        elif c.anim_in == "scale_fade":
            alpha_in = ease_out_expo(entry_p)
            y_pos    = c.target_y
            scale    = 0.95 + 0.05 * alpha_in
        else: # slide_up
            alpha_in = ease_out_expo(entry_p)
            dy       = int(c.slide_px_in * (1.0 - alpha_in))
            y_pos    = c.target_y + dy
            scale    = 1.0

        x_pos = c.target_x
        alpha = min(1.0, alpha_in)

        # Animations de sortie
        if t >= c.t_exit_start:
            exit_p = min((t - c.t_exit_start) / max(c.exit_dur, 1e-6), 1.0)

            if c.anim_out == "hard_swipe_up":
                exit_ease = ease_in_expo(exit_p) # Part lentement, explose à la fin
                y_pos    -= int(c.slide_px_out * exit_ease)
                alpha     = alpha * (1.0 - exit_ease**2) # Disparaît sur les dernières frames
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
    max_per_tableau:   int = 3,
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

        if len(current) >= max_per_tableau:
            flush()

        current.append(entry)

        if clean and clean[-1] in ".!?":
            flush()

    flush()
    return [t for t in tableaux if t]


# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class SubtitleBurner:

    VID_W = 1080
    VID_H = 1920
    SAFE_W = 880              # V15 : ~80% de l'écran en largeur
    CY     = 1920 // 2        # Centre parfait verticalement

    # V15 : Typographie Géante (Pour réussir le Squint Test)
    FS_IMPACT = 280           # Mots d'impact énormes (Les mots courts feront 1/3 écran)
    FS_NORMAL = 180           # Mots standards (Très gros)
    FS_STOP   = 120           # Mots de liaison (Discrets mais lisibles)
    FS_BADGE  = 180           # Badges géants

    GAP          = 45           # Espace augmenté pour aérer les polices géantes
    ENTRY_DUR    = 0.18         
    STAGGER      = 0.08         
    EXIT_DUR     = 0.16         
    GHOST_OP     = 0.20         
    BREATH_GAP   = 0.20         
    SLIDE_IN_PX  = 80           
    SLIDE_OUT_PX = 600          # Sortie expéditive vers le haut (Hard Wipe)

    STOP_WORDS = {
        "le","la","les","un","une","des","ce","ces","de","du","à","au",
        "et","en","ne","se","sa","son","ses","on","y","il","elle","ils",
        "elles","je","tu","nous","vous","qui","que","quoi","dont","où",
        "si","or","ni","car","mais","ou","donc","par","sur","sous","avec",
        "pour","dans","vers","chez","c'est","the","a","an","in","on","at",
        "to","for","of","and","is","it","be","as","by","we","he","they","you"
    }
    KEYWORDS_ACCENT = {
        "profit","gain","hausse","succès","argent","million","croissance",
        "résultat","stratégie","système","secret","clé","winner","champion",
        "elite","premium","ratio","liquidité","banques","traders","trading",
        "payout","funded","record","parfait","puissance","simplicité"
    }
    KEYWORDS_MUTED = {
        "perdre","perte","crash","chute","danger","stop","scam","arnaque",
        "faillite","ruine","échec","jamais","alerte","attention","amateur"
    }

    SFX_MAP = {
        "ACTION":  "click",
        "ACCENT":  "click",
        "BADGE":   "click_deep",
        "MUTED":   "swoosh",
        "STOP":    None,      # Pas de bruit pour les petits mots
        "PAUSE":   None,
    }

    def __init__(
        self,
        model_size:   str = "base",
        platform:     str = "shorts",
        font:         str = "Inter-Black",     # V15 : Extra lourd par défaut
        font_regular: str = "Inter-Medium",    # V15 : Plus propre pour liaison
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
Title: Nexus V15 Massive Typography
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TekiyoBold,{font},{self.FS_NORMAL},&H001F1D1D&,&H000000FF,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,4,0,1,0,1,2,{mh},{mh},{safe_v},1
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

        # V15 : Analyse sémantique frame par frame avec polices gigantesques
        for idx, (start, end, text) in enumerate(entries):
            clean = self.strip_tags(text)
            sem   = self.get_semantic_class(text)

            is_badge = (sem == "BADGE" or bool(re.search(r'\d+[\$€%]|[\$€]\d+', clean)))

            if sem == "STOP":
                fs      = self.FS_STOP
                bold    = False
                color   = TEXT_DIM_RGB
                anim_in = "fade_in"  # Discret
            elif sem in ["ACCENT", "MUTED", "ACTION"] or is_badge:
                fs      = self.FS_IMPACT
                bold    = True
                color   = ACCENT_RGB if sem == "ACCENT" else (MUTED_RGB if sem == "MUTED" else TEXT_RGB)
                anim_in = "pop_overshoot" if is_badge or sem in ["ACCENT", "MUTED"] else "slide_up"
            else:
                fs      = self.FS_NORMAL
                bold    = True
                color   = TEXT_RGB
                anim_in = "slide_up"

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

            # Audio Pre-Strike (-0.04s pour que l'image frappe juste avant le son)
            t_start     = max(0.0, start + idx * self.STAGGER - 0.04)
            t_entry_end = t_start + self.ENTRY_DUR

            # Hard Wipe à la sortie
            if next_tab_start is not None:
                t_exit_start = next_tab_start - self.EXIT_DUR * 0.5
                t_full_end   = next_tab_start + self.ENTRY_DUR
                anim_out     = "hard_swipe_up"
            else:
                t_exit_start = end - self.EXIT_DUR
                t_full_end   = end + 0.1
                anim_out     = "fade_out"

            anim_in = "scale_fade" if is_conclusion else anim_ins[idx]

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

        print(f"🎬  Massive Typography V15 — {len(timeline)} scènes…")

        tableaux = group_into_tableaux(timeline, max_per_tableau=3)
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
        bg       = BG_RGB
        duration = video_clip.duration
        fps      = video_clip.fps or 30

        def make_frame(t):
            return _compose_frame(t, all_clips, vid_w, vid_h, bg=bg)

        from moviepy.editor import VideoClip as MpVideoClip
        sub_layer = MpVideoClip(make_frame, duration=duration).set_fps(fps)

        if video_clip.audio is not None:
            sub_layer = sub_layer.set_audio(video_clip.audio)

        return sub_layer

    # =========================================================================
    # WHISPER PATH (génération ASS — inchangé)
    # =========================================================================

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
                    txt = c["text"].replace("\\", "")
                    sem = self.get_semantic_class(txt)
                    sty = "TekiyoBold" if sem in ("ACTION", "ACCENT") else "TekiyoRegular"
                    pop = r"{\fscx90\fscy90\alpha&HFF&\t(0,220,\fscx100\fscy100\alpha&H00&)}"
                    f.write(f"Dialogue: 0,{st},{en},{sty},,0,0,0,,{pop}{txt}\n")
            return True
        except Exception as e:
            print(f"❌  Whisper error: {e}")
            return False