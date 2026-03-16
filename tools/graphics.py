# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V29: Primitives graphiques — corrections radius + CTA card.
#
# DELTA V29 vs V22:
#   1. render_broll_card(): corner_radius 0.064→0.036 (mesuré: 21px@576p = 39px@1080p)
#   2. render_broll_card(): width ratio 0.524→0.530 (305/576 mesuré)
#   3. render_cta_card(): NOUVEAU — TikTok logo + searchbar pill sur fond navy
#   4. render_search_pill(): NOUVEAU — pill searchbar avec icônes vectorielles

from __future__ import annotations
import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from typing import Optional, Tuple
from pathlib import Path

from .config import (
    ASSET_DICT, ASSET_DIR, TEXT_RGB, TEXT_DIM_RGB,
    ACCENT_GRADIENT_LEFT, ACCENT_GRADIENT_RIGHT,
    BROLL_CARD_WIDTH_RATIO, BROLL_CARD_RADIUS_RATIO,
    BROLL_SHADOW_BLUR, BROLL_SHADOW_OPACITY,
    CTA_BG_COLOR, CTA_LOGO_CENTER_Y_RATIO,
    CTA_SEARCH_CENTER_Y_RATIO, CTA_SEARCH_WIDTH_RATIO,
    CTA_SEARCH_HEIGHT_RATIO, CTA_TIKTOK_HANDLE,
    FS_BASE, FS_MIN,
)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Chargement de police
# ══════════════════════════════════════════════════════════════════════════════

_FONT_CANDIDATES = {
    "regular": [
        "Inter-Regular.ttf", "Montserrat-Regular.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "semibold": [
        "Inter-SemiBold.ttf", "Inter-Medium.ttf", "Montserrat-SemiBold.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf", "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "bold": [
        "Inter-Bold.ttf", "Montserrat-Bold.ttf", "Poppins-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "extrabold": [
        "Inter-ExtraBold.ttf", "Inter-Black.ttf", "Montserrat-ExtraBold.ttf",
        "C:\\Windows\\Fonts\\impact.ttf", "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

_font_cache: dict = {}


def find_font(weight: str = "semibold", size: int = None) -> ImageFont.FreeTypeFont:
    if size is None:
        size = FS_BASE
    cache_key = (weight, size)
    if cache_key in _font_cache:
        return _font_cache[cache_key]
    candidates = _FONT_CANDIDATES.get(weight, _FONT_CANDIDATES["regular"])
    for fp in candidates:
        if fp and os.path.exists(str(fp)):
            try:
                font = ImageFont.truetype(fp, size)
                _font_cache[cache_key] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default()
    _font_cache[cache_key] = font
    return font


def measure_text(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * int(font.size * 0.6), font.size


def auto_size_font(
    text:         str,
    weight:       str,
    initial_size: int,
    max_w:        int,
    min_size:     int = FS_MIN,
) -> Tuple[ImageFont.FreeTypeFont, int, int, int]:
    size = initial_size
    while size >= min_size:
        font   = find_font(weight=weight, size=size)
        tw, th = measure_text(text, font)
        if tw <= max_w:
            return font, size, tw, th
        size -= 4
    font   = find_font(weight=weight, size=min_size)
    tw, th = measure_text(text, font)
    return font, min_size, tw, th


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Rendu texte RGBA
# ══════════════════════════════════════════════════════════════════════════════

def render_text_solid(
    text:     str,
    size:     int,
    weight:   str   = "semibold",
    color:    tuple = TEXT_RGB,
    max_w:    int   = 920,
    inverted: bool  = False,
) -> np.ndarray:
    font, final_size, tw, th = auto_size_font(text, weight, size, max_w)
    pad_x, pad_y = 36, 36
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    shadow_col   = (120, 120, 120) if not inverted else (0, 0, 0)
    shadow_alpha = 20

    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ds     = ImageDraw.Draw(shadow)
    ds.text((pad_x + 1, pad_y + 3), text, font=font, fill=shadow_col + (shadow_alpha,))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))

    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    dc     = ImageDraw.Draw(canvas)
    dc.text((pad_x, pad_y), text, font=font, fill=color + (255,))

    result = Image.alpha_composite(shadow, canvas)
    return np.array(result)


def render_text_gradient(
    text:        str,
    size:        int,
    weight:      str   = "bold",
    color_left:  tuple = ACCENT_GRADIENT_LEFT,
    color_right: tuple = ACCENT_GRADIENT_RIGHT,
    max_w:       int   = 920,
) -> np.ndarray:
    font, final_size, tw, th = auto_size_font(text, weight, size, max_w)
    pad_x, pad_y = 36, 36
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    mask_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    dm       = ImageDraw.Draw(mask_img)
    dm.text((pad_x, pad_y), text, font=font, fill=(255, 255, 255, 255))
    mask_arr = np.array(mask_img)

    grad = np.zeros((ch, cw, 3), dtype=np.float32)
    for x in range(cw):
        t = x / max(cw - 1, 1)
        r = color_left[0] + (color_right[0] - color_left[0]) * t
        g = color_left[1] + (color_right[1] - color_left[1]) * t
        b = color_left[2] + (color_right[2] - color_left[2]) * t
        grad[:, x, :] = [r, g, b]

    alpha  = mask_arr[:, :, 3:4].astype(np.float32) / 255.0
    result = np.zeros((ch, cw, 4), dtype=np.uint8)
    rgb    = (grad * alpha).clip(0, 255).astype(np.uint8)
    result[:, :, :3] = rgb
    result[:, :, 3]  = mask_arr[:, :, 3]
    return result


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 3 — Chargement d'assets image
# ══════════════════════════════════════════════════════════════════════════════

def load_asset_image(keyword: str) -> Optional[np.ndarray]:
    filename = ASSET_DICT.get(keyword.lower())
    if not filename:
        return None
    for search_dir in [ASSET_DIR, Path(".")]:
        asset_path = search_dir / filename
        if asset_path.exists():
            try:
                img = Image.open(asset_path).convert("RGBA")
                return np.array(img)
            except Exception:
                return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 4 — B-Roll Card (V29: radius CORRIGÉ 0.036, width CORRIGÉ 0.530)
# ══════════════════════════════════════════════════════════════════════════════

def render_broll_card(
    image_path:     str,
    canvas_w:       int,
    corner_radius:  int   = None,
    shadow_blur:    int   = None,
    shadow_opacity: float = None,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V29: B-Roll card avec valeurs DÉFINITIVES.

    ┌────────────────────┬──────────────┬──────────────┬─────────────────────┐
    │ Paramètre          │ V25          │ V29 (mesuré) │ Méthode             │
    ├────────────────────┼──────────────┼──────────────┼─────────────────────┤
    │ card_width         │ W × 0.524    │ W × 0.530    │ 305px / 576px       │
    │ corner_radius      │ W × 0.064    │ W × 0.036    │ bord courbe tracé   │
    │                    │              │ = 39px@1080p │ 21px@576p mesuré    │
    │ shadow_opacity     │ 0.33         │ 0.33         │ confirmé            │
    │ shadow_pad         │ 40px         │ 40px         │ confirmé            │
    └────────────────────┴──────────────┴──────────────┴─────────────────────┘
    """
    card_w  = int(canvas_w * BROLL_CARD_WIDTH_RATIO)
    # ARCHITECTURE_MASTER_V29: ratio 0.036 = 21px@576p = 39px@1080p (CORRIGÉ)
    radius  = corner_radius if corner_radius is not None else int(canvas_w * BROLL_CARD_RADIUS_RATIO)
    s_blur  = shadow_blur    if shadow_blur    is not None else BROLL_SHADOW_BLUR
    s_opa   = shadow_opacity if shadow_opacity is not None else BROLL_SHADOW_OPACITY

    try:
        img_pil = Image.open(image_path).convert("RGBA")
    except Exception:
        img_pil = Image.new("RGBA", (card_w, card_w), (30, 30, 30, 255))

    ratio   = card_w / max(img_pil.width, 1)
    card_h  = int(img_pil.height * ratio)
    img_pil = img_pil.resize((card_w, card_h), Image.LANCZOS)

    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius, fill=255
    )
    img_pil.putalpha(mask)

    shadow_pad = 40
    shadow_w   = card_w + shadow_pad * 2
    shadow_h   = card_h + shadow_pad * 2
    shadow     = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))

    smask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(smask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius,
        fill=int(s_opa * 255)
    )
    shadow_color = Image.new("RGBA", (card_w, card_h), (0, 0, 0, int(s_opa * 255)))
    shadow.paste(shadow_color, (shadow_pad, shadow_pad + 4), mask=smask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(s_blur))
    shadow.paste(img_pil, (shadow_pad, shadow_pad), mask=img_pil.split()[3])

    return np.array(shadow)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 5 — CTA Card (V29 NOUVEAU)
# ══════════════════════════════════════════════════════════════════════════════

def _render_tiktok_logo_vector(size: int) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V29: Logo TikTok vectoriel (approximation PIL).

    Le logo TikTok est une note de musique stylisée avec:
    - Corps principal: blanc
    - Ombre teal (cyan) décalée à gauche
    - Ombre rouge décalée à droite
    Taille paramétrique: size px (côté du carré conteneur)
    """
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # Le logo est centré dans le carré
    # Proportions basées sur le logo officiel SVG
    cx, cy = size // 2, size // 2
    body_w = int(size * 0.35)
    body_h = int(size * 0.55)
    stem_w = int(size * 0.12)
    note_r = int(size * 0.18)

    # Note de musique simplifiée: ellipse + tige
    def draw_note(draw_ref, offset_x, offset_y, color):
        # Ellipse (tête de la note, bas)
        ex = cx + offset_x - note_r
        ey = cy + offset_y + int(size * 0.15)
        draw_ref.ellipse([ex, ey, ex + note_r*2, ey + note_r*2], fill=color)
        # Tige (droite, montant)
        sx = cx + offset_x + note_r - stem_w
        sy = cy + offset_y - int(size * 0.30)
        draw_ref.rectangle([sx, sy, sx + stem_w, ey + note_r], fill=color)
        # Courbe supérieure droite (tête de courche)
        hx = sx
        hy = sy
        draw_ref.ellipse([hx - int(size*0.10), hy,
                          hx + int(size*0.20), hy + int(size*0.22)], fill=color)

    # Ombre teal (gauche)
    draw_note(draw, -int(size * 0.04), 0, (0, 242, 234, 200))
    # Ombre rouge (droite)
    draw_note(draw, int(size * 0.04), 0, (255, 0, 80, 200))
    # Corps blanc
    draw_note(draw, 0, 0, (255, 255, 255, 255))

    return np.array(canvas)


def _render_search_pill(
    width:   int,
    height:  int,
    handle:  str = "@tekiyo_",
    bg:      tuple = (255, 255, 255),
    text_color: tuple = (30, 30, 30),
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V29: Search bar pill avec icônes.

    Layout mesuré (cta_0030.png):
      - BG blanc, contour fin gris clair
      - Icône loupe à gauche (noir)
      - Texte handle centré (gris foncé)
      - Mini logo TikTok à droite (rouge/cyan)
    """
    radius = height // 2
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # Fond blanc arrondi
    draw.rounded_rectangle([0, 0, width-1, height-1], radius=radius, fill=bg+(255,))
    # Contour léger
    draw.rounded_rectangle([0, 0, width-1, height-1], radius=radius,
                            outline=(180, 180, 185, 255), width=2)

    icon_size  = int(height * 0.55)
    pad        = int(height * 0.25)

    # Icône loupe (cercle + ligne)
    lx, ly = pad, (height - icon_size) // 2
    sr = int(icon_size * 0.38)
    draw.ellipse([lx, ly, lx + sr*2, ly + sr*2], outline=(80, 80, 80, 255), width=2)
    lp = int(sr * 0.70)
    draw.line([lx + sr + lp - 2, ly + sr + lp - 2,
               lx + icon_size, ly + icon_size],
              fill=(80, 80, 80, 255), width=3)

    # Texte handle
    font_size = max(20, int(height * 0.40))
    font      = find_font("semibold", font_size)
    tw, th    = measure_text(handle, font)
    tx        = (width - tw) // 2
    ty        = (height - th) // 2
    draw.text((tx, ty), handle, font=font, fill=text_color + (255,))

    # Mini logo TikTok droite (deux cercles colorés)
    rx    = width - pad - icon_size
    ry    = (height - icon_size) // 2
    cr    = icon_size // 4
    # teal
    draw.ellipse([rx + cr, ry, rx + cr + cr*2, ry + cr*2],
                 fill=(0, 200, 180, 200))
    # rouge
    draw.ellipse([rx + cr + int(cr*0.7), ry, rx + cr + int(cr*0.7) + cr*2, ry + cr*2],
                 fill=(255, 0, 60, 200))
    # blanc centre (overlap)
    draw.ellipse([rx + cr + int(cr*0.35), ry + int(cr*0.15),
                  rx + cr + int(cr*0.35) + int(cr*1.3), ry + int(cr*0.15) + int(cr*1.3)],
                 fill=(255, 255, 255, 255))

    return np.array(canvas)


def render_cta_card(
    canvas_w:     int,
    canvas_h:     int,
    handle:       str   = None,
    logo_scale:   float = 1.0,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V29: CTA card TikTok complète sur fond navy.

    COMPOSANTS (mesurés sur cta_0030.png / 576×1024):
      1. Fond: rgb(14,14,26) navy plein canvas
      2. Logo TikTok (taille ~0.20W) centré à Y=0.461H
      3. Texte "TikTok" (white, bold) sous le logo
      4. Search pill (@handle) centré à Y=0.571H, width=0.618W

    Returns: RGBA array canvas_w × canvas_h
    """
    if handle is None:
        handle = CTA_TIKTOK_HANDLE

    canvas_arr = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    # Fond navy
    canvas_arr[:, :, 0] = CTA_BG_COLOR[0]
    canvas_arr[:, :, 1] = CTA_BG_COLOR[1]
    canvas_arr[:, :, 2] = CTA_BG_COLOR[2]
    canvas_arr[:, :, 3] = 255

    canvas = Image.fromarray(canvas_arr, mode="RGBA")

    # ── Logo TikTok ──────────────────────────────────────────────────────────
    logo_size = int(canvas_w * 0.20 * logo_scale)
    logo_arr  = _render_tiktok_logo_vector(logo_size)
    logo_img  = Image.fromarray(logo_arr, mode="RGBA")

    logo_cx = (canvas_w - logo_size) // 2
    logo_cy = int(canvas_h * CTA_LOGO_CENTER_Y_RATIO) - logo_size // 2 - int(canvas_h * 0.06)
    canvas.paste(logo_img, (logo_cx, logo_cy), mask=logo_img.split()[3])

    # ── Texte "TikTok" ───────────────────────────────────────────────────────
    tt_font_size = max(30, int(canvas_w * 0.085))
    tt_font      = find_font("bold", tt_font_size)
    tt_tw, tt_th = measure_text("TikTok", tt_font)
    tt_x         = (canvas_w - tt_tw) // 2
    tt_y         = logo_cy + logo_size + int(canvas_h * 0.012)

    draw = ImageDraw.Draw(canvas)
    draw.text((tt_x, tt_y), "TikTok", font=tt_font, fill=(255, 255, 255, 255))

    # ── Search bar pill ───────────────────────────────────────────────────────
    pill_w = int(canvas_w * CTA_SEARCH_WIDTH_RATIO)
    pill_h = int(canvas_h * CTA_SEARCH_HEIGHT_RATIO)
    pill_h = max(pill_h, 40)

    pill_arr = _render_search_pill(pill_w, pill_h, handle)
    pill_img = Image.fromarray(pill_arr, mode="RGBA")

    pill_x = (canvas_w - pill_w) // 2
    pill_y = int(canvas_h * CTA_SEARCH_CENTER_Y_RATIO) - pill_h // 2
    canvas.paste(pill_img, (pill_x, pill_y), mask=pill_img.split()[3])

    return np.array(canvas)