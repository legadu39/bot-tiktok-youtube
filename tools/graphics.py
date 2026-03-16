# -*- coding: utf-8 -*-
# ARCHITECTURE_MASTER_V31: Primitives graphiques — correction position logo CTA.
# PIXEL_PERFECT_V34: FIX 1 — find_font() avec détection et logging de dégradation
# PIXEL_PERFECT_V34: FIX 5 — generate_procedural_broll_card() pour vault vide
#
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DELTA V34 vs V31                                                            ║
# ╠══════════════════════════════════════════════════════════════════════════════╣
# ║                                                                              ║
# ║  FIX #1 — find_font(): Logging de dégradation (NOUVEAU V34)                ║
# ║    V31: fallback silencieux sur DejaVuSans sans avertissement               ║
# ║    V34: détecte si la police chargée est "premium" (Inter, Montserrat...)   ║
# ║         ou "dégradée" (DejaVu, Arial system font) et log le statut         ║
# ║    Impact: permet de diagnostiquer la cause #1 de dégradation typographique ║
# ║                                                                              ║
# ║  FIX #5 — generate_procedural_broll_card() (NOUVEAU V34)                   ║
# ║    V31: vault vide → fonds blancs statiques monotones                       ║
# ║    V34: génère une card B-Roll typographique procédurale avec:              ║
# ║         - Fond dégradé (palette selon classe sémantique du texte)           ║
# ║         - Contenu textuel extrait de la scène                               ║
# ║         - Corner radius, shadow, style premium                              ║
# ║    Compatible avec render_broll_card() → utilisable dans broll_schedule     ║
# ║                                                                              ║
# ║  CONSERVÉ V31 (aucun changement):                                           ║
# ║    render_broll_card(): valeurs V31 confirmées ✓                            ║
# ║    render_cta_card(): position logo 0.374H corrigée V31 ✓                  ║
# ║    render_text_solid() / render_text_gradient() — inchangés ✓               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

from __future__ import annotations
import os
import math
import re
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

try:
    from .config import CTA_TIKTOK_TEXT_Y_RATIO
except ImportError:
    CTA_TIKTOK_TEXT_Y_RATIO = 0.459


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Chargement de police (FIX 1: logging de dégradation)
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

# PIXEL_PERFECT_V34: FIX 1 — Polices "premium" (Inter, Neue Haas, Montserrat, Poppins, SF)
# Si la font chargée n'est pas dans cette liste, c'est une dégradation à signaler.
_PREMIUM_FONT_KEYWORDS = {
    "inter", "neue", "haas", "montserrat", "poppins", "sf", "gilroy",
    "proxima", "circular", "futura", "helvetica"
}

# PIXEL_PERFECT_V34: FIX 1 — Tracking de l'état premium pour ne logger qu'une fois
_font_premium_status: dict = {}
_font_cache: dict = {}


def find_font(weight: str = "semibold", size: int = None) -> ImageFont.FreeTypeFont:
    """
    PIXEL_PERFECT_V34: FIX 1 — find_font() avec logging de dégradation.

    Changements vs V31:
        - Détecte si la police chargée est premium (Inter, Montserrat...) ou dégradée
        - Log un WARNING visible si fallback sur DejaVu/Arial (cause principale de
          dégradation typographique silencieuse)
        - Log ✅ au premier chargement d'une police premium par weight
        - Le cache reste identique (aucun impact perf)

    Dégradation typographique détectée en production:
        Inter absent → DejaVuSans-Bold chargé silencieusement
        → police à chasse fixe vs grotesque moderne
        → poids visuel très différent (pas d'ExtraBold disponible)
        → kerning et spacing non conformes à la référence

    Pour installer Inter (recommandé):
        https://rsms.me/inter/ → Inter-ExtraBold.ttf, Inter-SemiBold.ttf, Inter-Regular.ttf
        Placer dans le dossier du projet ou dans C:/Windows/Fonts/
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
                font_name = Path(fp).stem.lower()

                # PIXEL_PERFECT_V34: FIX 1 — Détection premium vs dégradé
                is_premium = any(kw in font_name for kw in _PREMIUM_FONT_KEYWORDS)

                # Ne logger qu'une fois par weight pour éviter le spam
                if weight not in _font_premium_status:
                    _font_premium_status[weight] = is_premium
                    if is_premium:
                        print(
                            f"✅ PIXEL_PERFECT_V34: Font premium [{weight}]: "
                            f"{Path(fp).stem} @ {size}px"
                        )
                    else:
                        print(
                            f"⚠️  PIXEL_PERFECT_V34: Font DÉGRADÉE [{weight}]: "
                            f"{Path(fp).stem} @ {size}px\n"
                            f"   → Inter absent. Qualité typographique réduite.\n"
                            f"   → Installer: https://rsms.me/inter/\n"
                            f"   → Fichiers requis: Inter-ExtraBold.ttf, "
                            f"Inter-SemiBold.ttf, Inter-Regular.ttf"
                        )

                _font_cache[cache_key] = font
                return font
            except Exception:
                continue

    # PIXEL_PERFECT_V34: FIX 1 — Log critique si AUCUNE font trouvée
    if weight not in _font_premium_status:
        _font_premium_status[weight] = False
        print(
            f"🚨 PIXEL_PERFECT_V34: AUCUNE FONT trouvée pour weight={weight}!\n"
            f"   → Utilisation du font de secours PIL (qualité très dégradée)\n"
            f"   → Installer Inter depuis https://rsms.me/inter/"
        )

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
# BLOC 2 — Rendu texte RGBA (inchangé V31)
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
    """
    ARCHITECTURE_MASTER_V31: Gradient TEAL→PINK (corrigé via config_v31.py).
    color_left  = ACCENT_GRADIENT_LEFT  = (105,228,220) TEAL (début du mot, gauche)
    color_right = ACCENT_GRADIENT_RIGHT = (208,122,148) PINK (fin du mot, droite)
    """
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
# BLOC 3 — Chargement d'assets image (inchangé V31)
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
# BLOC 4 — B-Roll Card procédurale (FIX 5: NOUVEAU V34)
# ══════════════════════════════════════════════════════════════════════════════

def generate_procedural_broll_card(
    scene_text:   str,
    output_path:  str,
    canvas_w:     int   = 1080,
    scene_index:  int   = 0,
    is_hook:      bool  = False,
) -> str:
    """
    PIXEL_PERFECT_V34: FIX 5 — Génère une card B-Roll typographique procédurale.

    But: remplacer le fond blanc statique monotone (44/44 vault misses)
    par un élément visuel pertinent généré à partir du contenu de la scène.

    Layout:
        - Width  : canvas_w × 0.530 (identique à BROLL_CARD_WIDTH_RATIO)
        - Height : card_w × 0.55 (ratio horizontal premium)
        - Radius : canvas_w × 0.036 (identique à BROLL_CARD_RADIUS_RATIO)
        - Shadow  : pad=40px, blur=18, opacity=0.33 (identique à render_broll_card)

    Contenu:
        - Texte extrait de la scène (3 mots max, tags [BOLD]/[LIGHT] retirés)
        - Affichage en grande typographie centrée (fontsize = card_h × 0.28)
        - Si chiffre/% : badge vert émeraude (ACCENT_RGB)
        - Si mot positif : fond violet dégradé (premium branding)
        - Sinon : fond light grey avec texte anthracite

    Palettes:
        "number"  → (123,44,191) violet → (80,15,130) | texte blanc
        "accent"  → (105,228,220) teal  → (45,175,168) | texte anthracite
        "hook"    → (25,25,31) noir     → (14,14,26) navy | texte blanc (style inversion)
        "normal"  → (245,245,247) light → (220,220,225) | texte (25,25,25)

    Compatibilité:
        Le fichier PNG produit est compatible avec render_broll_card() et
        peut être passé directement dans broll_schedule[(t_start, t_end, path)].

    Returns:
        str: chemin vers le fichier PNG généré
    """
    card_w  = int(canvas_w * 0.530)
    card_h  = int(card_w * 0.55)
    radius  = int(canvas_w * 0.036)

    # PIXEL_PERFECT_V34: Extraction et nettoyage du texte
    clean   = re.sub(r'\[(?:BOLD|LIGHT|BADGE|PAUSE)\]', '', scene_text, flags=re.IGNORECASE).strip()
    words   = [w for w in clean.split() if re.sub(r'[^\w]', '', w)]
    display = ' '.join(words[:3]) if words else "—"

    # PIXEL_PERFECT_V34: Détection du type de contenu pour la palette
    has_number  = any(re.search(r'[\d%€$£]', w) for w in words)
    has_accent  = any(
        w.lower().rstrip('.,!?') in {
            "secret", "profit", "gain", "winner", "argent", "succès",
            "champion", "payout", "capital", "système", "méthode",
            "révèle", "découverte", "clé", "maîtrise", "stratégie"
        }
        for w in words
    )

    # Palette : (bg_top, bg_bottom, text_color)
    if is_hook or (scene_index == 0):
        # Hook → noir premium (style inversion #1 de la référence)
        bg_top    = (25,  25,  31)
        bg_bottom = (14,  14,  26)
        text_col  = (255, 255, 255)
    elif has_number:
        # Chiffre/stat → violet premium (accent branding)
        bg_top    = (123, 44,  191)
        bg_bottom = (80,  15,  130)
        text_col  = (255, 255, 255)
    elif has_accent:
        # Mot positif → teal gradient (ACCENT_GRADIENT côté gauche)
        bg_top    = (105, 228, 220)
        bg_bottom = (45,  175, 168)
        text_col  = (25,  25,  25)
    else:
        # Normal → light grey (fond neutre premium)
        bg_top    = (245, 245, 247)
        bg_bottom = (220, 220, 225)
        text_col  = (25,  25,  25)

    # ── Construction de la card ──────────────────────────────────────────────
    shadow_pad = 40
    total_w    = card_w + shadow_pad * 2
    total_h    = card_h + shadow_pad * 2

    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))

    # Shadow (identique à render_broll_card)
    smask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(smask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius, fill=int(0.33 * 255)
    )
    shadow_col_layer = Image.new("RGBA", (card_w, card_h), (0, 0, 0, int(0.33 * 255)))
    shadow_full      = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    shadow_full.paste(shadow_col_layer, (shadow_pad, shadow_pad + 4), mask=smask)
    shadow_full = shadow_full.filter(ImageFilter.GaussianBlur(18))
    canvas      = Image.alpha_composite(canvas, shadow_full)

    # Card body avec dégradé vertical ligne par ligne
    card      = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)

    for y in range(card_h):
        t = y / max(card_h - 1, 1)
        r = int(bg_top[0] + (bg_bottom[0] - bg_top[0]) * t)
        g = int(bg_top[1] + (bg_bottom[1] - bg_top[1]) * t)
        b = int(bg_top[2] + (bg_bottom[2] - bg_top[2]) * t)
        card_draw.line([(0, y), (card_w - 1, y)], fill=(r, g, b, 255))

    # Mask arrondi
    card_mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=radius, fill=255
    )
    card.putalpha(card_mask)

    # Accent line (barre colorée haut de la card, style UI premium)
    if has_number or is_hook:
        accent_line = Image.new("RGBA", (card_w, 6), (0, 0, 0, 0))
        accent_draw = ImageDraw.Draw(accent_line)
        for x in range(card_w):
            t     = x / max(card_w - 1, 1)
            r_acc = int(ACCENT_GRADIENT_LEFT[0] + (ACCENT_GRADIENT_RIGHT[0] - ACCENT_GRADIENT_LEFT[0]) * t)
            g_acc = int(ACCENT_GRADIENT_LEFT[1] + (ACCENT_GRADIENT_RIGHT[1] - ACCENT_GRADIENT_LEFT[1]) * t)
            b_acc = int(ACCENT_GRADIENT_LEFT[2] + (ACCENT_GRADIENT_RIGHT[2] - ACCENT_GRADIENT_LEFT[2]) * t)
            accent_draw.line([(x, 0), (x, 5)], fill=(r_acc, g_acc, b_acc, 255))
        # Arrondi haut seulement (les 6px du haut de la card)
        accent_arr = np.array(accent_line)
        card_arr   = np.array(card)
        # Paste la barre colorée sur les 6 premières lignes de la card
        card_arr[:6, :, :3] = accent_arr[:, :card_w, :3]
        card_arr[:6, :, 3]  = np.minimum(
            card_arr[:6, :, 3],
            accent_arr[:, :card_w, 3]
        )
        card = Image.fromarray(card_arr, mode="RGBA")
        card.putalpha(card_mask)  # Re-appliquer le mask après merge

    # Texte centré
    font_size = max(FS_MIN, int(card_h * 0.28))
    font      = find_font("extrabold", font_size)

    try:
        bbox = font.getbbox(display)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(display) * int(font_size * 0.6), font_size

    # Auto-shrink si texte trop large
    while tw > card_w - 32 and font_size > FS_MIN:
        font_size -= 4
        font       = find_font("extrabold", font_size)
        try:
            bbox   = font.getbbox(display)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(display) * int(font_size * 0.6), font_size

    text_x = (card_w - tw) // 2
    text_y = (card_h - th) // 2

    card_text_draw = ImageDraw.Draw(card)

    # Drop shadow du texte (subtil)
    card_text_draw.text(
        (text_x + 1, text_y + 2),
        display,
        font=font,
        fill=(0, 0, 0, 60),
    )
    # Texte principal
    card_text_draw.text(
        (text_x, text_y),
        display,
        font=font,
        fill=text_col + (255,),
    )

    # Paste card sur canvas (avec shadow)
    canvas.paste(card, (shadow_pad, shadow_pad), mask=card.split()[3])

    # Sauvegarde
    canvas.save(output_path, "PNG")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 5 — B-Roll Card (inchangé V31)
# ══════════════════════════════════════════════════════════════════════════════

def render_broll_card(
    image_path:     str,
    canvas_w:       int,
    corner_radius:  int   = None,
    shadow_blur:    int   = None,
    shadow_opacity: float = None,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V29/V31: B-Roll card — valeurs confirmées V31 (inchangées).
    """
    card_w  = int(canvas_w * BROLL_CARD_WIDTH_RATIO)
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
# BLOC 6 — CTA Card (V31: position logo CORRIGÉE — inchangé V34)
# ══════════════════════════════════════════════════════════════════════════════

def _render_tiktok_logo_vector(size: int) -> np.ndarray:
    """ARCHITECTURE_MASTER_V29/V31: Logo TikTok vectoriel (inchangé V34)."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    cx, cy = size // 2, size // 2
    stem_w = int(size * 0.12)
    note_r = int(size * 0.18)

    def draw_note(draw_ref, offset_x, offset_y, color):
        ex = cx + offset_x - note_r
        ey = cy + offset_y + int(size * 0.15)
        draw_ref.ellipse([ex, ey, ex + note_r*2, ey + note_r*2], fill=color)
        sx = cx + offset_x + note_r - stem_w
        sy = cy + offset_y - int(size * 0.30)
        draw_ref.rectangle([sx, sy, sx + stem_w, ey + note_r], fill=color)
        hx = sx
        hy = sy
        draw_ref.ellipse([hx - int(size*0.10), hy,
                          hx + int(size*0.20), hy + int(size*0.22)], fill=color)

    draw_note(draw, -int(size * 0.04), 0, (0, 242, 234, 200))
    draw_note(draw, int(size * 0.04), 0, (255, 0, 80, 200))
    draw_note(draw, 0, 0, (255, 255, 255, 255))

    return np.array(canvas)


def _render_search_pill(
    width:      int,
    height:     int,
    handle:     str   = "@tekiyo_",
    bg:         tuple = (255, 255, 255),
    text_color: tuple = (30, 30, 30),
) -> np.ndarray:
    """ARCHITECTURE_MASTER_V29/V31: Search bar pill (inchangée V34)."""
    radius = height // 2
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    draw.rounded_rectangle([0, 0, width-1, height-1], radius=radius, fill=bg+(255,))
    draw.rounded_rectangle([0, 0, width-1, height-1], radius=radius,
                            outline=(180, 180, 185, 255), width=2)

    icon_size = int(height * 0.55)
    pad       = int(height * 0.25)

    lx, ly = pad, (height - icon_size) // 2
    sr = int(icon_size * 0.38)
    draw.ellipse([lx, ly, lx + sr*2, ly + sr*2], outline=(80, 80, 80, 255), width=2)
    lp = int(sr * 0.70)
    draw.line([lx + sr + lp - 2, ly + sr + lp - 2,
               lx + icon_size, ly + icon_size],
              fill=(80, 80, 80, 255), width=3)

    font_size = max(20, int(height * 0.40))
    font      = find_font("semibold", font_size)
    tw, th    = measure_text(handle, font)
    tx        = (width - tw) // 2
    ty        = (height - th) // 2
    draw.text((tx, ty), handle, font=font, fill=text_color + (255,))

    rx = width - pad - icon_size
    ry = (height - icon_size) // 2
    cr = icon_size // 4
    draw.ellipse([rx + cr, ry, rx + cr + cr*2, ry + cr*2],
                 fill=(0, 200, 180, 200))
    draw.ellipse([rx + cr + int(cr*0.7), ry, rx + cr + int(cr*0.7) + cr*2, ry + cr*2],
                 fill=(255, 0, 60, 200))
    draw.ellipse([rx + cr + int(cr*0.35), ry + int(cr*0.15),
                  rx + cr + int(cr*0.35) + int(cr*1.3), ry + int(cr*0.15) + int(cr*1.3)],
                 fill=(255, 255, 255, 255))

    return np.array(canvas)


def render_cta_card(
    canvas_w:   int,
    canvas_h:   int,
    handle:     str   = None,
    logo_scale: float = 1.0,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V31: CTA card TikTok complète (inchangée V34).
    Position logo corrigée V31: CTA_LOGO_CENTER_Y_RATIO=0.374H.
    """
    if handle is None:
        handle = CTA_TIKTOK_HANDLE

    canvas_arr = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    canvas_arr[:, :, 0] = CTA_BG_COLOR[0]
    canvas_arr[:, :, 1] = CTA_BG_COLOR[1]
    canvas_arr[:, :, 2] = CTA_BG_COLOR[2]
    canvas_arr[:, :, 3] = 255

    canvas = Image.fromarray(canvas_arr, mode="RGBA")

    logo_size = int(canvas_w * 0.20 * logo_scale)
    logo_arr  = _render_tiktok_logo_vector(logo_size)
    logo_img  = Image.fromarray(logo_arr, mode="RGBA")

    logo_cx = (canvas_w - logo_size) // 2
    logo_cy = int(canvas_h * CTA_LOGO_CENTER_Y_RATIO) - logo_size // 2
    canvas.paste(logo_img, (logo_cx, logo_cy), mask=logo_img.split()[3])

    tt_font_size = max(30, int(canvas_w * 0.085))
    tt_font      = find_font("bold", tt_font_size)
    tt_tw, tt_th = measure_text("TikTok", tt_font)
    tt_x         = (canvas_w - tt_tw) // 2
    tt_y         = int(canvas_h * CTA_TIKTOK_TEXT_Y_RATIO) - tt_th // 2

    draw = ImageDraw.Draw(canvas)
    draw.text((tt_x, tt_y), "TikTok", font=tt_font, fill=(255, 255, 255, 255))

    pill_w = int(canvas_w * CTA_SEARCH_WIDTH_RATIO)
    pill_h = int(canvas_h * CTA_SEARCH_HEIGHT_RATIO)
    pill_h = max(pill_h, 40)

    pill_arr = _render_search_pill(pill_w, pill_h, handle)
    pill_img = Image.fromarray(pill_arr, mode="RGBA")

    pill_x = (canvas_w - pill_w) // 2
    pill_y = int(canvas_h * CTA_SEARCH_CENTER_Y_RATIO) - pill_h // 2
    canvas.paste(pill_img, (pill_x, pill_y), mask=pill_img.split()[3])

    return np.array(canvas)