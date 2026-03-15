# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Primitives de rendu graphique — CORRIGÉES.
#
# CORRECTIONS PRINCIPALES vs V9:
#   1. render_broll_card(): corner_radius ratio 0.042→0.064 (mesuré left_inset=37px@576p)
#   2. render_broll_card(): shadow_opacity 0.25→0.33 (mesuré pixel diff=84/255)
#   3. render_broll_card(): center Y ratio 0.5→0.4717 (mesuré 483/1024)
#   4. render_text_solid(): couleur shadow (0,0,0)→subtle (pas de shadow noir dur)
#   5. find_font(): FS_BASE 80→75 (corrigé depuis mesures)

from __future__ import annotations
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from typing import Optional, Tuple
from pathlib import Path

from .config import (
    ASSET_DICT, ASSET_DIR, TEXT_RGB, TEXT_DIM_RGB,
    ACCENT_GRADIENT_LEFT, ACCENT_GRADIENT_RIGHT,
    BROLL_CARD_WIDTH_RATIO, BROLL_CARD_RADIUS_RATIO,
    BROLL_SHADOW_BLUR, BROLL_SHADOW_OPACITY,
    FS_BASE, FS_MIN,
)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Chargement de police
# ══════════════════════════════════════════════════════════════════════════════

_FONT_CANDIDATES = {
    "regular": [
        "Inter-Regular.ttf", "Inter_Regular.ttf",
        "Montserrat-Regular.ttf", "Poppins-Regular.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "semibold": [
        "Inter-SemiBold.ttf", "Inter-Medium.ttf",
        "Montserrat-SemiBold.ttf", "Poppins-SemiBold.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "bold": [
        "Inter-Bold.ttf", "Inter_Bold.ttf",
        "Montserrat-Bold.ttf", "Poppins-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "extrabold": [
        "Inter-ExtraBold.ttf", "Inter-Black.ttf",
        "Montserrat-ExtraBold.ttf", "Montserrat-Black.ttf",
        "C:\\Windows\\Fonts\\impact.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

_font_cache: dict = {}


def find_font(weight: str = "semibold", size: int = None) -> ImageFont.FreeTypeFont:
    """
    ARCHITECTURE_MASTER_V22: Chargement police avec cascade et cache.
    Défaut size=FS_BASE (75px, corrigé depuis 80px).
    """
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
    """Retourne (width, height) du texte rendu avec la police."""
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * int(font.size * 0.6), font.size


def auto_size_font(
    text:       str,
    weight:     str,
    initial_size: int,
    max_w:      int,
    min_size:   int = FS_MIN,
) -> Tuple[ImageFont.FreeTypeFont, int, int, int]:
    """
    ARCHITECTURE_MASTER_V22: Ajustement automatique de la taille de police.
    Réduit progressivement jusqu'à ce que le texte tienne dans max_w.

    Returns: (font, final_size, text_w, text_h)
    """
    size = initial_size
    while size >= min_size:
        font       = find_font(weight=weight, size=size)
        tw, th     = measure_text(text, font)
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
    text:      str,
    size:      int,
    weight:    str   = "semibold",
    color:     tuple = TEXT_RGB,
    max_w:     int   = 920,
    inverted:  bool  = False,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22: Rendu texte couleur unie avec ombre subtile.

    CORRECTION: ombre très subtile (opacité 8%, blur 12px).
    La référence montre quasi-aucune ombre — texte propre sur fond blanc.
    """
    font, final_size, tw, th = auto_size_font(text, weight, size, max_w)

    pad_x, pad_y = 36, 36
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    # Ombre très subtile (~8% opacité, confirmé: quasi-invisible dans la référence)
    shadow_col  = (120, 120, 120) if not inverted else (0, 0, 0)
    shadow_alpha = 20  # 8% opacité (était 13 ≈ 5%, légèrement augmenté)

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
    """
    ARCHITECTURE_MASTER_V22: Texte avec gradient horizontal — CONFIRMÉ frame 75.

    Mesures frame 75 "marché.":
        left pixels:  rgb(190,115,218) à x≈239 — violet
        right pixels: rgb(134,108,169) à x≈329 — mauve
        gradient type: LINÉAIRE (pas de courbe), horizontal pur

    Algorithme:
        1. Rendre le texte en blanc sur RGBA transparent (masque alpha)
        2. Générer gradient horizontal linéaire W pixels
        3. Multiplier gradient × canal alpha du masque
    """
    font, final_size, tw, th = auto_size_font(text, weight, size, max_w)

    pad_x, pad_y = 36, 36
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    # Masque alpha — texte blanc sur transparent
    mask_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    dm       = ImageDraw.Draw(mask_img)
    dm.text((pad_x, pad_y), text, font=font, fill=(255, 255, 255, 255))
    mask_arr = np.array(mask_img)

    # Gradient horizontal linéaire (interpolation pixel par pixel)
    grad = np.zeros((ch, cw, 3), dtype=np.float32)
    for x in range(cw):
        t = x / max(cw - 1, 1)
        r = color_left[0] + (color_right[0] - color_left[0]) * t
        g = color_left[1] + (color_right[1] - color_left[1]) * t
        b = color_left[2] + (color_right[2] - color_left[2]) * t
        grad[:, x, :] = [r, g, b]

    # Combinaison: gradient × alpha masque
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
    """Charge une image d'asset depuis le dictionnaire."""
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
# BLOC 4 — B-Roll Card (CORRIGÉE)
# ══════════════════════════════════════════════════════════════════════════════

def render_broll_card(
    image_path:     str,
    canvas_w:       int,
    corner_radius:  int   = None,
    shadow_blur:    int   = None,
    shadow_opacity: float = None,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22: Card B-roll CORRIGÉE depuis mesures pixel.

    CORRECTIONS vs V9:
    ┌────────────────────┬──────────────┬──────────────┬─────────────────────┐
    │ Paramètre          │ Ancien (V9)  │ Nouveau (V22)│ Source              │
    ├────────────────────┼──────────────┼──────────────┼─────────────────────┤
    │ card_width         │ W × 0.53     │ W × 0.533    │ 307/576 mesuré      │
    │ corner_radius      │ W × 0.042    │ W × 0.064    │ left_inset=37@576p  │
    │ shadow_opacity     │ 0.25         │ 0.33         │ diff=84/255 mesuré  │
    │ shadow_offset_y    │ +16px        │ +4px         │ shadow dès le bord  │
    │ shadow_blur        │ 18px         │ 18px         │ confirmé            │
    └────────────────────┴──────────────┴──────────────┴─────────────────────┘

    Returns: numpy RGBA array prêt pour composition.
    """
    # Dimensions avec valeurs corrigées
    card_w  = int(canvas_w * BROLL_CARD_WIDTH_RATIO)
    radius  = corner_radius if corner_radius is not None else int(canvas_w * BROLL_CARD_RADIUS_RATIO)
    s_blur  = shadow_blur    if shadow_blur    is not None else BROLL_SHADOW_BLUR
    s_opa   = shadow_opacity if shadow_opacity is not None else BROLL_SHADOW_OPACITY

    # Chargement et redimensionnement de l'image
    try:
        img_pil = Image.open(image_path).convert("RGBA")
    except Exception:
        img_pil = Image.new("RGBA", (card_w, card_w), (30, 30, 30, 255))

    ratio   = card_w / max(img_pil.width, 1)
    card_h  = int(img_pil.height * ratio)
    img_pil = img_pil.resize((card_w, card_h), Image.LANCZOS)

    # Masque coins arrondis — rayon CORRIGÉ (0.064 au lieu de 0.042)
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius, fill=255
    )
    img_pil.putalpha(mask)

    # ARCHITECTURE_MASTER_V22: Shadow CORRIGÉE
    # Mesure: shadow visible dès le bord exact de la card (dy=0, diff=84)
    # → shadow_offset_y réduit à 4px (était 16px en V9 = trop décalé)
    shadow_pad = 40  # padding autour pour que shadow ne soit pas clippée
    shadow_w   = card_w + shadow_pad * 2
    shadow_h   = card_h + shadow_pad * 2
    shadow     = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))

    smask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(smask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius,
        fill=int(s_opa * 255)
    )
    shadow_color = Image.new("RGBA", (card_w, card_h), (0, 0, 0, int(s_opa * 255)))
    # CORRIGÉ: offset +4px au lieu de +16px — shadow colle au bord de la card
    shadow.paste(shadow_color, (shadow_pad, shadow_pad + 4), mask=smask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(s_blur))

    # Composite: ombre + image
    shadow.paste(img_pil, (shadow_pad, shadow_pad), mask=img_pil.split()[3])

    return np.array(shadow)