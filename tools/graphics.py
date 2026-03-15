# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V22: Primitives de rendu graphique.
# Inclut le rendu de texte avec gradient horizontal (mesuré dans la référence).
#
# DÉCOUVERTE RÉFÉRENCE (frame 3 "marché.") :
#   - Gradient horizontal gauche→droite
#   - Couleur gauche : rgb(190,115,218) — violet
#   - Couleur droite : rgb(134,108,169) — mauve
#   - Pas de dégradé vertical, uniquement horizontal

from __future__ import annotations
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from typing import Optional, Tuple
from pathlib import Path

from .config import (
    ASSET_DICT, ASSET_DIR, TEXT_RGB, TEXT_DIM_RGB,
    ACCENT_GRADIENT_LEFT, ACCENT_GRADIENT_RIGHT,
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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}


def find_font(weight: str = "semibold", size: int = 75) -> ImageFont.FreeTypeFont:
    """
    ARCHITECTURE_MASTER_V22 : Chargement de police avec cascade.
    weight='semibold' est le défaut car c'est ce qu'utilise la référence
    pour les mots normaux (pas bold, pas regular — semibold).
    """
    candidates = _FONT_CANDIDATES.get(weight, _FONT_CANDIDATES["regular"])
    for fp in candidates:
        if fp and os.path.exists(str(fp)):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def measure_text(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """Retourne (width, height) du texte avec la police donnée."""
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * int(font.size * 0.6), font.size


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Rendu texte RGBA (avec et sans gradient)
# ══════════════════════════════════════════════════════════════════════════════

def render_text_solid(
    text:      str,
    size:      int,
    weight:    str  = "semibold",
    color:     tuple = TEXT_RGB,
    max_w:     int   = 920,
    inverted:  bool  = False,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22 : Rendu texte couleur unie + ombre subtile.

    Ombre : Gaussian blur 16px, opacité 5% (très subtil comme la référence).
    Padding : 40px pour que l'ombre ne soit pas clippée.
    """
    shadow_col = (200, 200, 200) if inverted else (0, 0, 0)
    font       = find_font(weight=weight, size=size)
    tw, th     = measure_text(text, font)

    # Réduction automatique si trop large
    while tw > max_w and size > 20:
        size -= 4
        font  = find_font(weight=weight, size=size)
        tw, th = measure_text(text, font)

    pad_x, pad_y = 40, 40
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    # Ombre (très subtile — 5% opacité comme la référence)
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ds     = ImageDraw.Draw(shadow)
    ds.text((pad_x, pad_y + 4), text, font=font, fill=shadow_col + (13,))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))

    # Texte
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
    ARCHITECTURE_MASTER_V22 : Rendu texte avec gradient horizontal.

    REVERSE ENGINEERING FRAME 3 "marché." :
    • Gradient gauche→droite : violet(190,115,218) → mauve(134,108,169)
    • Gradient linéaire pixel-par-pixel (pas de courbe)
    • Appliqué comme masque de couleur sur le texte rendu en alpha

    Algorithme :
        1. Rendre le texte en blanc sur fond transparent (masque alpha)
        2. Créer un gradient horizontal pleine largeur
        3. Multiplier gradient par masque alpha
    """
    font   = find_font(weight=weight, size=size)
    tw, th = measure_text(text, font)

    while tw > max_w and size > 20:
        size -= 4
        font  = find_font(weight=weight, size=size)
        tw, th = measure_text(text, font)

    pad_x, pad_y = 40, 40
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    # Masque alpha (texte blanc)
    mask_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    dm       = ImageDraw.Draw(mask_img)
    dm.text((pad_x, pad_y), text, font=font, fill=(255, 255, 255, 255))
    mask_arr = np.array(mask_img)

    # Gradient horizontal
    grad = np.zeros((ch, cw, 3), dtype=np.float32)
    for x in range(cw):
        t = x / max(cw - 1, 1)
        r = color_left[0] + (color_right[0] - color_left[0]) * t
        g = color_left[1] + (color_right[1] - color_left[1]) * t
        b = color_left[2] + (color_right[2] - color_left[2]) * t
        grad[:, x, :] = [r, g, b]

    # Combinaison : gradient × alpha du masque
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


def render_broll_card(
    image_path:    str,
    canvas_w:      int,
    corner_radius: int  = None,
    shadow_blur:   int  = 18,
    shadow_opacity: float = 0.25,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V22 : Card B-roll avec coins arrondis et ombre portée.

    REVERSE ENGINEERING FRAME 8 (iPhone 17 PRO card) :
    • Largeur card : 53% du canvas (305/576)
    • Corner radius : ~24px à 576px → ratio 0.042 → 45px à 1080px
    • Ombre : Gaussian blur 18px, opacité 25%
    • Centré horizontalement, Y légèrement au-dessus du centre

    card_w = int(canvas_w * 0.53)
    radius = corner_radius or int(canvas_w * 0.042)
    """
    card_w = int(canvas_w * 0.53)
    radius = corner_radius if corner_radius is not None else int(canvas_w * 0.042)

    try:
        img_pil = Image.open(image_path).convert("RGBA")
    except Exception:
        img_pil = Image.new("RGBA", (card_w, card_w), (30, 30, 30, 255))

    # Redimensionner proportionnellement
    ratio   = card_w / max(img_pil.width, 1)
    card_h  = int(img_pil.height * ratio)
    img_pil = img_pil.resize((card_w, card_h), Image.LANCZOS)

    # Masque coin arrondi
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius, fill=255
    )
    img_pil.putalpha(mask)

    # Ombre portée
    shadow_w = card_w + 60
    shadow_h = card_h + 60
    shadow   = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))

    smask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(smask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius,
        fill=int(shadow_opacity * 255)
    )
    shadow_color = Image.new("RGBA", (card_w, card_h), (0, 0, 0, int(shadow_opacity * 255)))
    shadow.paste(shadow_color, (30, 24), mask=smask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))

    # Composite : ombre + image
    shadow.paste(img_pil, (10, 10), mask=img_pil.split()[3])

    return np.array(shadow)