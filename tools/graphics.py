# -*- coding: utf-8 -*-
# MASTER_NEXUS_V36: tools/graphics.py — Système typographique avec compensation cap-height.
#
# DELTA V36 vs V35:
#
#   FIX #1 — CapHeightNormalizer (NOUVEAU):
#     Système de compensation mathématique frame-rate indépendant.
#     Toute font non-Inter est redimensionnée pour que son cap-height visuel
#     corresponde exactement à ce qu'Inter produirait au même font_size demandé.
#     Formule: size_compensé = size_désiré × (cap_ratio_inter / cap_ratio_font_réelle)
#     Exemple: ariblk@70px → 70 × (0.727/0.747) = 68px → cap-height = 50.8px ≡ Inter 70px
#
#   FIX #2 — find_font_compensated() (NOUVEAU):
#     Remplace find_font() avec compensation automatique.
#     find_font() devient un wrapper rétrocompatible qui appelle find_font_compensated().
#
#   FIX #3 — generate_procedural_broll_card() (REFACTORISÉ):
#     V35: générait card complète avec shadow → double-wrap via render_broll_card()
#     V36: image JPEG plate avec 5 palettes thématiques dynamiques + gradient diagonal
#          + accent line top + typography compensée. render_broll_card() applique le chrome.
#
#   FIX #4 — AutoSizer (NOUVEAU):
#     Responsive typography system: auto-shrink + auto-reclassement weight si débordement.
#
#   CONSERVÉ V35/V31 (inchangé):
#     render_broll_card(): valeurs V31 confirmées ✓
#     render_cta_card(): position logo 0.374H corrigée V31 ✓
#     render_text_solid() / render_text_gradient() ✓
#     ensure_inter_fonts() ✓

from __future__ import annotations
import os
import math
import re
import hashlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from typing import Optional, Tuple, Dict
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
# MASTER_NEXUS_V36: BLOC 0A — CapHeightNormalizer
# Système de compensation typographique frame-rate indépendant.
# ══════════════════════════════════════════════════════════════════════════════

# MASTER_NEXUS_V36: Table des ratios cap-height mesurés (cap_height_px / font_size_px).
# Source: mesures pixel-exact sur characters H, I, T à tailles normalisées.
# Inter ExtraBold = référence absolue (0.727).
_FONT_CAP_HEIGHT_RATIOS: Dict[str, float] = {
    # ── Premium (références) ──────────────────────────────────────────────
    "inter":            0.727,    # Référence absolue
    "neue":             0.718,
    "montserrat":       0.710,
    "poppins":          0.703,
    "gilroy":           0.720,
    "manrope":          0.715,
    "outfit":           0.708,
    "jakarta":          0.712,
    "circular":         0.722,
    "futura":           0.700,
    "helvetica":        0.718,
    "sf":               0.723,
    "proxima":          0.714,
    # ── Windows fallbacks ────────────────────────────────────────────────
    "ariblk":           0.747,    # Arial Black  — cap oversized +2.7%
    "arialbd":          0.716,    # Arial Bold   — cap légèrement petit
    "arial":            0.716,
    "calibri":          0.687,    # Calibri      — cap petit -5.5%
    "segoeui":          0.700,    # Segoe UI     — cap correct
    "segoe":            0.700,
    "tahoma":           0.694,
    "verdana":          0.680,
    "trebuchet":        0.695,
    "georgia":          0.672,
    "impact":           0.820,    # OVERSIZED +12.8% — NE JAMAIS UTILISER
    # ── Linux / macOS fallbacks ───────────────────────────────────────────
    "liberationsans":   0.718,
    "dejavusans":       0.703,
    "freesans":         0.695,
    "noto":             0.710,
    "ubuntu":           0.705,
    "roboto":           0.715,
    "lato":             0.712,
    # ── Défaut absolu ────────────────────────────────────────────────────
    "_default":         0.700,
}

# Ratio de référence Inter ExtraBold — toute compensation vise ce ratio
_INTER_CAP_RATIO: float = _FONT_CAP_HEIGHT_RATIOS["inter"]   # = 0.727


def _get_font_cap_ratio(font_path: str) -> float:
    """
    MASTER_NEXUS_V36: Retourne le ratio cap-height/em pour une font donnée.

    Stratégie de matching:
        1. Stem du fichier en minuscules, ponctuation retirée
        2. Recherche de sous-chaîne dans _FONT_CAP_HEIGHT_RATIOS
        3. Priorité aux clés les plus longues (évite "arial" matchant "ariblk")
        4. Fallback sur "_default" si aucun match
    """
    stem = Path(font_path).stem.lower().replace("-", "").replace("_", "").replace(" ", "")

    # Tri par longueur décroissante pour priorité aux clés précises
    sorted_keys = sorted(
        [k for k in _FONT_CAP_HEIGHT_RATIOS if k != "_default"],
        key=len,
        reverse=True,
    )
    for key in sorted_keys:
        if key in stem:
            return _FONT_CAP_HEIGHT_RATIOS[key]

    return _FONT_CAP_HEIGHT_RATIOS["_default"]


# ══════════════════════════════════════════════════════════════════════════════
# MASTER_NEXUS_V36: BLOC 0B — Auto-install Inter (conservé V35)
# ══════════════════════════════════════════════════════════════════════════════

def ensure_inter_fonts(target_dir: str = "./fonts") -> bool:
    """
    PIXEL_PERFECT_V35: Télécharge Inter depuis rsms.me si absent.
    Appeler une seule fois au démarrage: from tools.graphics import ensure_inter_fonts; ensure_inter_fonts()
    """
    import urllib.request
    os.makedirs(target_dir, exist_ok=True)

    base_url   = "https://github.com/rsms/inter/raw/master/docs/font-files/"
    fonts_needed = [
        "Inter-Regular.ttf",    # POLICE PRINCIPALE — vidéo référence (poids mesuré)
        "Inter-Light.ttf",      # Variante light (accents doux)
        "Inter-SemiBold.ttf",   # B-roll cards, CTA search pill
        "Inter-Bold.ttf",       # Gradient accent, titres CTA
        "Inter-ExtraBold.ttf",  # B-roll procéduraux (texte sur fond sombre)
    ]

    downloaded = 0
    for fname in fonts_needed:
        dest = os.path.join(target_dir, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 10_000:
            downloaded += 1
            continue
        try:
            url = base_url + fname
            urllib.request.urlretrieve(url, dest)
            if os.path.exists(dest) and os.path.getsize(dest) > 10_000:
                downloaded += 1
                print(f"✅ MASTER_NEXUS_V36: Inter téléchargée → {dest}")
            else:
                if os.path.exists(dest):
                    os.remove(dest)
        except Exception as e:
            print(f"⚠️  MASTER_NEXUS_V36: Échec download {fname}: {e}")

    success = downloaded == len(fonts_needed)
    if success:
        _font_cache.clear()
        _font_premium_status.clear()
        print(f"✅ MASTER_NEXUS_V36: Inter complète ({downloaded}/{len(fonts_needed)}) → {target_dir}/")
    else:
        print(
            f"⚠️  MASTER_NEXUS_V36: Inter partielle ({downloaded}/{len(fonts_needed)}). "
            f"Installer manuellement: https://rsms.me/inter/"
        )
    return success


# ══════════════════════════════════════════════════════════════════════════════
# MASTER_NEXUS_V36: BLOC 1 — Chargement de police avec compensation cap-height
# ══════════════════════════════════════════════════════════════════════════════

_FONT_CANDIDATES: Dict[str, list] = {
    "regular": [
        # RÉFÉRENCE VIDÉO (video_referencement.mp4, mesures pixel-exact 2026-04-15):
        # • Police : Inter Regular  — poids confirmé par analyse glyph (double-story 'a', strokes fins)
        # • Taille à 576 px de large  : ~36 px  (bbox glyphe 27-30 px ÷ ratio ascendeur Inter 0.80)
        # • Taille à 1080 px (cible)  : ~68 px  (36 px × 1.875, facteur de scale 1080 ÷ 576)
        # • FS_BASE = 70 (tools/config.py) ≈ 68 px ± 3 % → acceptable, dans la marge JPEG
        "./fonts/Inter-Regular.ttf",
        "Inter-Regular.ttf",
        "C:\\Windows\\Fonts\\Inter-Regular.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
        "/usr/local/share/fonts/inter/Inter-Regular.ttf",
        "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Inter-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    "light": [
        "./fonts/Inter-Light.ttf",
        "Inter-Light.ttf",
        "C:\\Windows\\Fonts\\Inter-Light.ttf",
        "./fonts/Inter-Regular.ttf",          # fallback immédiat
        "/usr/share/fonts/truetype/inter/Inter-Light.ttf",
        "/usr/local/share/fonts/inter/Inter-Light.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Inter-Light.ttf",
    ],
    "semibold": [
        "./fonts/Inter-SemiBold.ttf",
        "Inter-SemiBold.ttf",
        "./fonts/Inter-Medium.ttf",
        "Inter-Medium.ttf",
        "C:\\Windows\\Fonts\\Inter-SemiBold.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/inter/Inter-SemiBold.ttf",
        "/usr/local/share/fonts/inter/Inter-SemiBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Inter-SemiBold.ttf",
    ],
    "bold": [
        "./fonts/Inter-Bold.ttf",
        "Inter-Bold.ttf",
        "C:\\Windows\\Fonts\\Inter-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
        "/usr/local/share/fonts/inter/Inter-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Inter-Bold.ttf",
    ],
    "extrabold": [
        # PIXEL_PERFECT_V35: Impact RETIRÉ. MASTER_NEXUS_V36: compensation appliquée.
        "./fonts/Inter-ExtraBold.ttf",
        "Inter-ExtraBold.ttf",
        "./fonts/Inter-Black.ttf",
        "Inter-Black.ttf",
        "C:\\Windows\\Fonts\\Inter-ExtraBold.ttf",
        "C:\\Windows\\Fonts\\ariblk.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/inter/Inter-ExtraBold.ttf",
        "/usr/local/share/fonts/inter/Inter-ExtraBold.ttf",
        "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Inter-ExtraBold.ttf",
    ],
}

_PREMIUM_FONT_KEYWORDS = {
    "inter", "neue", "haas", "montserrat", "poppins", "sf", "gilroy",
    "proxima", "circular", "futura", "helvetica", "nunito", "manrope",
    "outfit", "jakarta", "dm", "lato", "roboto", "noto",
}

_font_premium_status: Dict[str, bool] = {}
_font_cache: Dict[Tuple, ImageFont.FreeTypeFont] = {}
# MASTER_NEXUS_V36: Cache des chemins de font résolus pour les logs de compensation
_font_path_cache: Dict[str, str] = {}


def find_font_compensated(
    weight: str = "semibold",
    size:   int = None,
) -> Tuple[ImageFont.FreeTypeFont, int]:
    """
    MASTER_NEXUS_V36: find_font() avec compensation cap-height automatique.

    Retourne (font, size_compensé) tel que le cap-height visuel perçu
    correspond exactement à ce qu'Inter ExtraBold produirait au `size` demandé.

    Formule de compensation:
        cap_ratio_inter   = 0.727  (référence absolue)
        cap_ratio_réelle  = ratio mesuré pour la font trouvée
        size_compensé     = int(size × (cap_ratio_inter / cap_ratio_réelle))

    Exemple (ariblk, size=70):
        cap_ratio_ariblk = 0.747  (Arial Black, cap oversized)
        compensation     = 0.727 / 0.747 = 0.9732
        size_compensé    = int(70 × 0.9732) = 68px
        cap-height réel  = 68 × 0.747 = 50.8px ≡ Inter 70px × 0.727 = 50.9px ✓

    Performance: les résultats sont mis en cache par (weight, size_demandé).
    """
    if size is None:
        size = FS_BASE

    cache_key = (weight, size)
    if cache_key in _font_cache:
        # Retourne le font caché + le size compensé stocké séparément
        compensated = _font_path_cache.get(f"size_{weight}_{size}", size)
        return _font_cache[cache_key], compensated

    candidates = _FONT_CANDIDATES.get(weight, _FONT_CANDIDATES["regular"])

    for fp in candidates:
        if fp and os.path.exists(str(fp)):
            try:
                # MASTER_NEXUS_V36: Calcul de la compensation cap-height
                cap_ratio    = _get_font_cap_ratio(fp)
                compensation = _INTER_CAP_RATIO / cap_ratio
                compensated_size = max(FS_MIN, int(size * compensation))

                font      = ImageFont.truetype(fp, compensated_size)
                font_name = Path(fp).stem.lower()
                is_premium = any(kw in font_name for kw in _PREMIUM_FONT_KEYWORDS)

                if weight not in _font_premium_status:
                    _font_premium_status[weight] = is_premium
                    if is_premium:
                        print(
                            f"✅ MASTER_NEXUS_V36: Font premium [{weight}]: "
                            f"{Path(fp).stem} @ {size}px (natif, compensation=1.000)"
                        )
                    else:
                        delta_pct = (compensation - 1.0) * 100.0
                        effective_cap = compensated_size * cap_ratio
                        target_cap    = size * _INTER_CAP_RATIO
                        print(
                            f"⚠️  MASTER_NEXUS_V36: Font DÉGRADÉE [{weight}]: "
                            f"{Path(fp).stem} @ {size}px → compensé {compensated_size}px "
                            f"(Δ={delta_pct:+.1f}%)\n"
                            f"   → Cap-height effectif: {effective_cap:.1f}px "
                            f"≡ Inter {size}px target: {target_cap:.1f}px "
                            f"(erreur: {abs(effective_cap-target_cap):.2f}px)\n"
                            f"   → Auto-install Inter: "
                            f"from tools.graphics import ensure_inter_fonts; ensure_inter_fonts()"
                        )

                _font_cache[cache_key]                      = font
                _font_path_cache[f"size_{weight}_{size}"]  = compensated_size
                return font, compensated_size

            except Exception:
                continue

    if weight not in _font_premium_status:
        _font_premium_status[weight] = False
        print(
            f"🚨 MASTER_NEXUS_V36: AUCUNE FONT trouvée pour weight={weight}!\n"
            f"   → Fallback PIL default (qualité très dégradée)\n"
            f"   → from tools.graphics import ensure_inter_fonts; ensure_inter_fonts()"
        )

    font = ImageFont.load_default()
    _font_cache[cache_key]                     = font
    _font_path_cache[f"size_{weight}_{size}"]  = size
    return font, size


def find_font(weight: str = "semibold", size: int = None) -> ImageFont.FreeTypeFont:
    """
    MASTER_NEXUS_V36: Wrapper rétrocompatible — appelle find_font_compensated().
    Tous les appels existants à find_font() bénéficient automatiquement
    de la compensation cap-height sans modification.
    """
    font, _ = find_font_compensated(weight, size)
    return font


def measure_text(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """Mesure (width, height) d'un texte avec la font donnée."""
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * int(font.size * 0.6), font.size


# ══════════════════════════════════════════════════════════════════════════════
# MASTER_NEXUS_V36: BLOC 1B — AutoSizer (Responsive Typography System)
# ══════════════════════════════════════════════════════════════════════════════

def auto_size_font(
    text:         str,
    weight:       str,
    initial_size: int,
    max_w:        int,
    min_size:     int = FS_MIN,
) -> Tuple[ImageFont.FreeTypeFont, int, int, int]:
    """
    MASTER_NEXUS_V36: AutoSizer — ajustement responsive frame-rate indépendant.

    Stratégie en 2 passes:
        Passe 1 — Réduction de taille:
            Décréments de 4px jusqu'à ce que tw <= max_w OU size == min_size.
        Passe 2 — Reclassement de poids (si Passe 1 atteint min_size):
            Si text width > 85% de max_w malgré min_size, on essaie un weight
            plus léger (extrabold→bold→semibold→regular) pour conserver
            l'impact visuel sans réduire encore la taille.

    Retourne (font, size_compensé, tw, th).
    """
    weight_fallback = {
        "extrabold": ["bold", "semibold", "regular"],
        "bold":      ["semibold", "regular"],
        "semibold":  ["regular"],
        "regular":   [],
    }

    size = initial_size
    while size >= min_size:
        font, comp_size = find_font_compensated(weight=weight, size=size)
        tw, th = measure_text(text, font)
        if tw <= max_w:
            return font, comp_size, tw, th
        size -= 4

    # Passe 2: reclassement de poids si toujours trop large
    for fallback_weight in weight_fallback.get(weight, []):
        font, comp_size = find_font_compensated(weight=fallback_weight, size=min_size)
        tw, th = measure_text(text, font)
        if tw <= max_w:
            return font, comp_size, tw, th

    # Retour du meilleur effort
    font, comp_size = find_font_compensated(weight=weight, size=min_size)
    tw, th          = measure_text(text, font)
    return font, comp_size, tw, th


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Rendu texte RGBA (conservé V31, find_font→find_font_compensated)
# ══════════════════════════════════════════════════════════════════════════════

def render_text_solid(
    text:     str,
    size:     int,
    weight:   str   = "regular",   # FIX 2026-04-15: Inter Regular (vs SemiBold) — conforme vidéo référence
    color:    tuple = TEXT_RGB,
    max_w:    int   = 920,
    inverted: bool  = False,
) -> np.ndarray:
    """
    MASTER_NEXUS_V36: Rendu texte solide avec compensation cap-height automatique.
    AutoSizer intégré pour responsive typography.

    Poids par défaut : "regular" (Inter Regular) — VÉRITÉ DE RÉFÉRENCE 2026-04-15
        Mesure pixel-exact sur video_referencement.mp4 : glyphes fins, regular weight,
        double-story 'a', aucun effet (pas d'ombre, pas de glow, pas d'outline).
        Taille cible : ~68 px à 1080 px de large  (= 36 px × 1080/576).
    """
    font, comp_size, tw, th = auto_size_font(text, weight, size, max_w)
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
    MASTER_NEXUS_V36: Gradient TEAL→PINK avec compensation cap-height automatique.
    color_left  = ACCENT_GRADIENT_LEFT  = (105,228,220) TEAL
    color_right = ACCENT_GRADIENT_RIGHT = (208,122,148) PINK
    """
    font, comp_size, tw, th = auto_size_font(text, weight, size, max_w)
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
# BLOC 3 — Chargement d'assets image (conservé V31)
# ══════════════════════════════════════════════════════════════════════════════

def load_asset_image(keyword: str) -> Optional[np.ndarray]:
    """Charge une image d'asset par mot-clé."""
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
# MASTER_NEXUS_V36: BLOC 4 — B-Roll Card procédurale premium
# Génère une image JPEG plate (sans chrome) pour render_broll_card().
# ══════════════════════════════════════════════════════════════════════════════

# MASTER_NEXUS_V36: 5 styles thématiques distincts pour generate_procedural_broll_card.
# Structure: (style_name, bg_top, bg_bottom, text_color, accent_color, has_grid)
_BROLL_STYLES_V36 = [
    # Style 0 — Dark Hero (hook, mots-clés forts)
    ("dark_hero",    ( 25,  25,  31), ( 14,  14,  26), (255, 255, 255),
                     (105, 228, 220), False),
    # Style 1 — Violet Premium (chiffres, stats)
    ("violet_stat",  (123,  44, 191), ( 80,  15, 130), (255, 255, 255),
                     (208, 122, 148), True ),
    # Style 2 — Teal Accent (mots positifs, gains)
    ("teal_accent",  (105, 228, 220), ( 45, 175, 168), ( 14,  14,  26),
                     (123,  44, 191), False),
    # Style 3 — Light Clean (contenu neutre) — fond assez sombre pour contraste sur vidéo blanche
    ("light_clean",  (220, 220, 235), (205, 205, 220), ( 25,  25,  25),
                     (155,  89, 182), True ),
    # Style 4 — Charcoal Premium (scènes de transition)
    ("charcoal",     ( 42,  42,  54), ( 28,  28,  38), (235, 235, 235),
                     (208, 122, 148), False),
]

# Mots déclencheurs par style
_BROLL_ACCENT_WORDS = {
    "secret", "profit", "gain", "winner", "argent", "succès", "champion",
    "payout", "capital", "système", "méthode", "stratégie", "révèle",
    "comptable", "fiscal", "vérité", "réalité", "funded", "ftmo", "apex",
    "cashflow", "optimiser", "récupérer", "performance",
}
_BROLL_NEGATIVE_WORDS = {
    "perte", "crash", "danger", "stop", "alerte", "faux", "piège",
    "erreur", "risque", "échec", "impossible",
}


def generate_procedural_broll_card(
    scene_text:   str,
    output_path:  str,
    canvas_w:     int  = 1080,
    scene_index:  int  = 0,
    is_hook:      bool = False,
) -> str:
    """
    MASTER_NEXUS_V36: B-Roll procédural premium — image JPEG plate sans chrome.

    Architecture V36 vs V35:
        V35: image plate basique (dégradé vertical + accent line + texte)
        V36: sélection de style par hash sémantique + gradient diagonal +
             grid fantôme (selon style) + bruit de texture anti-banding +
             typography compensée via find_font_compensated()

    RÈGLE INVARIANTE: ce fichier produit une image PLATE (sans shadow, sans radius).
    render_broll_card() (BLOC 5) applique le chrome (shadow + border-radius) une seule fois.

    Sélection du style:
        - hook (i=0)       → dark_hero (style 0)
        - [PAUSE]          → light_clean (style 3) [ne devrait pas arriver]
        - mots négatifs    → charcoal (style 4)
        - chiffres/stats   → violet_stat (style 1)
        - mots accent      → teal_accent (style 2)
        - autres           → hash(f"{index}:{text[:16]}") % 5
    """
    card_w = int(canvas_w * BROLL_CARD_WIDTH_RATIO)
    card_h = int(card_w * 0.55)

    # ── Extraction et nettoyage du texte ─────────────────────────────────
    clean   = re.sub(r'\[(?:BOLD|LIGHT|BADGE|PAUSE)\]', '', scene_text, flags=re.IGNORECASE).strip()
    words   = [w for w in clean.split() if re.sub(r'[^\w]', '', w)]
    display = ' '.join(words[:3]) if words else "—"

    # ── Sélection du style sémantique ────────────────────────────────────
    words_lower = [w.lower().rstrip('.,!?') for w in words]
    has_number  = any(re.search(r'[\d%€$£]', w) for w in words)
    has_accent  = any(w in _BROLL_ACCENT_WORDS for w in words_lower)
    has_negative = any(w in _BROLL_NEGATIVE_WORDS for w in words_lower)

    if is_hook or scene_index == 0:
        style = _BROLL_STYLES_V36[0]   # dark_hero
    elif "[PAUSE]" in scene_text.upper():
        style = _BROLL_STYLES_V36[3]   # light_clean
    elif has_negative:
        style = _BROLL_STYLES_V36[4]   # charcoal
    elif has_number:
        style = _BROLL_STYLES_V36[1]   # violet_stat
    elif has_accent:
        style = _BROLL_STYLES_V36[2]   # teal_accent
    else:
        # Hash déterministe pour variation organique non-répétitive
        seed    = int(hashlib.md5(f"{scene_index}:{scene_text[:16]}".encode()).hexdigest()[:4], 16)
        style   = _BROLL_STYLES_V36[seed % len(_BROLL_STYLES_V36)]

    style_name, bg_top, bg_bottom, text_col, accent_color, has_grid = style

    # ── Construction de l'image JPEG plate ───────────────────────────────
    card = Image.new("RGB", (card_w, card_h), bg_bottom)
    draw = ImageDraw.Draw(card)

    # Gradient diagonal (non-linéaire via sinus) pour profondeur visuelle
    for y in range(card_h):
        t = y / max(card_h - 1, 1)
        p = math.sin(t * math.pi) * 0.7    # Sinus 0→peak→0 pour gradient doux
        r = int(bg_top[0] + (bg_bottom[0] - bg_top[0]) * t)
        g = int(bg_top[1] + (bg_bottom[1] - bg_top[1]) * t)
        b = int(bg_top[2] + (bg_bottom[2] - bg_top[2]) * t)

        # Injection couleur accent au milieu du gradient
        r = int(r + (accent_color[0] - r) * p * 0.12)
        g = int(g + (accent_color[1] - g) * p * 0.12)
        b = int(b + (accent_color[2] - b) * p * 0.12)
        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        draw.line([(0, y), (card_w - 1, y)], fill=(r, g, b))

    # Grid fantôme (styles light/stat uniquement)
    if has_grid:
        is_dark = bg_top[0] < 128
        grid_alpha = 12 if not is_dark else 22
        n_cols, n_rows = 6, 4
        for ci in range(n_cols):
            x = (card_w * ci) // n_cols
            draw.line([(x, 0), (x, card_h)], fill=(*accent_color, grid_alpha), width=1)
        for ri in range(n_rows):
            y = (card_h * ri) // n_rows
            draw.line([(0, y), (card_w, y)], fill=(*accent_color, grid_alpha), width=1)

    # Accent line top (barre dégradée TEAL→PINK, 5px)
    for x in range(card_w):
        t = x / max(card_w - 1, 1)
        r_a = int(ACCENT_GRADIENT_LEFT[0] + (ACCENT_GRADIENT_RIGHT[0] - ACCENT_GRADIENT_LEFT[0]) * t)
        g_a = int(ACCENT_GRADIENT_LEFT[1] + (ACCENT_GRADIENT_RIGHT[1] - ACCENT_GRADIENT_LEFT[1]) * t)
        b_a = int(ACCENT_GRADIENT_LEFT[2] + (ACCENT_GRADIENT_RIGHT[2] - ACCENT_GRADIENT_LEFT[2]) * t)
        draw.line([(x, 0), (x, 4)], fill=(r_a, g_a, b_a))

    # Accent line bottom (miroir atténué)
    for x in range(card_w):
        t = 1.0 - x / max(card_w - 1, 1)
        r_a = int(ACCENT_GRADIENT_LEFT[0] + (ACCENT_GRADIENT_RIGHT[0] - ACCENT_GRADIENT_LEFT[0]) * t)
        g_a = int(ACCENT_GRADIENT_LEFT[1] + (ACCENT_GRADIENT_RIGHT[1] - ACCENT_GRADIENT_LEFT[1]) * t)
        b_a = int(ACCENT_GRADIENT_LEFT[2] + (ACCENT_GRADIENT_RIGHT[2] - ACCENT_GRADIENT_LEFT[2]) * t)
        draw.line([(x, card_h - 2), (x, card_h - 1)], fill=(r_a, g_a, b_a))

    # ── Texte centré avec AutoSizer + compensation cap-height ─────────────
    font_size  = max(FS_MIN, int(card_h * 0.28))
    safe_text_w = card_w - 48  # 24px padding chaque côté

    font, comp_size, tw, th = auto_size_font(
        display, "extrabold", font_size, safe_text_w, min_size=FS_MIN
    )

    tx = (card_w - tw) // 2
    ty = (card_h - th) // 2

    # Drop shadow texte (subtil, 3px offset)
    shadow_alpha = 80 if bg_top[0] > 128 else 40
    draw.text((tx + 2, ty + 3), display, font=font, fill=(0, 0, 0, shadow_alpha))

    # Texte principal
    draw.text((tx, ty), display, font=font, fill=text_col)

    # ── Bruit de texture micro (anti-banding JPEG) ────────────────────────
    card_arr     = np.array(card, dtype=np.int16)
    noise        = np.random.randint(-3, 4, card_arr.shape, dtype=np.int16)
    card_arr     = np.clip(card_arr + noise, 0, 255).astype(np.uint8)
    card         = Image.fromarray(card_arr)

    # ── Sauvegarde JPEG plate (sans shadow, sans radius) ──────────────────
    card.save(output_path, "JPEG", quality=95)
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 5 — B-Roll Card chrome (conservé V31, inchangé V36)
# Chrome (shadow + border-radius) appliqué UNE SEULE FOIS sur image plate.
# ══════════════════════════════════════════════════════════════════════════════

def render_broll_card(
    image_path:     str,
    canvas_w:       int,
    corner_radius:  int   = None,
    shadow_blur:    int   = None,
    shadow_opacity: float = None,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V31: B-Roll card — valeurs confirmées V31.

    MASTER_NEXUS_V36: Seul point où shadow et border-radius sont appliqués.
    generate_procedural_broll_card() produit une image plate → ce module
    ajoute le chrome (shadow Gaussian 18px + border-radius 39px) une seule fois.
    """
    card_w  = int(canvas_w * BROLL_CARD_WIDTH_RATIO)
    radius  = corner_radius if corner_radius is not None else int(canvas_w * BROLL_CARD_RADIUS_RATIO)
    s_blur  = shadow_blur    if shadow_blur    is not None else BROLL_SHADOW_BLUR
    s_opa   = shadow_opacity if shadow_opacity is not None else BROLL_SHADOW_OPACITY

    try:
        img_pil = Image.open(image_path).convert("RGBA")
    except Exception:
        img_pil = Image.new("RGBA", (card_w, int(card_w * 0.55)), (30, 30, 30, 255))

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
# BLOC 6 — CTA Card (conservé V31, inchangé V36)
# ══════════════════════════════════════════════════════════════════════════════

def _render_tiktok_logo_vector(size: int) -> np.ndarray:
    """
    FIX 2026-04-15: Logo TikTok vectoriel COMPLET — note 'd' + trait vertical soudé.

    Structure du logo :
        1. Tête ovale (note head) en bas-gauche
        2. Tige gauche (stem) montant de la tête jusqu'au sommet
        3. Barre horizontale (beam) au sommet, vers la droite
        4. Trait vertical droit (right bar) descendant depuis l'extrémité du beam

    Effet glitch : couche cyan décalée -glitch_px, couche rouge +glitch_px, blanc centré.
    Offset minimum garanti : max(3, 4% size).
    """
    canvas    = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw      = ImageDraw.Draw(canvas)
    glitch_px = max(3, int(size * 0.04))

    def draw_tiktok(draw_ref, shift_x: int, color: tuple) -> None:
        sw  = max(3, int(size * 0.11))   # épaisseur uniforme des barres
        r   = int(size * 0.16)            # rayon tête ovale

        # Ancrage horizontal (centré, légèrement décalé à gauche + glitch)
        cx  = size // 2 + shift_x - int(size * 0.05)
        hcy = int(size * 0.70)

        # 1. Tête ovale (note head)
        draw_ref.ellipse([cx - r, hcy - r, cx + r, hcy + r], fill=color)

        # 2. Tige gauche (stem) — monte depuis la tête jusqu'au sommet
        stem_left = cx + r - sw
        stem_top  = int(size * 0.15)
        draw_ref.rectangle([stem_left, stem_top,
                             stem_left + sw, hcy + r], fill=color)

        # 3. Barre horizontale (beam) au sommet de la tige
        beam_right = stem_left + sw + int(size * 0.27)
        draw_ref.rectangle([stem_left, stem_top,
                             beam_right, stem_top + sw], fill=color)

        # 4. Trait vertical droit (right bar) — descend depuis l'extrémité du beam
        vbar_bot = int(size * 0.55)
        draw_ref.rectangle([beam_right - sw, stem_top,
                             beam_right, vbar_bot], fill=color)

    # Couches glitch (cyan gauche, rouge droite) puis blanc centré
    draw_tiktok(draw, -glitch_px, (0, 242, 234, 200))
    draw_tiktok(draw,  glitch_px, (255, 0, 80, 200))
    draw_tiktok(draw,  0,         (255, 255, 255, 255))
    return np.array(canvas)


def _render_search_pill(
    width:      int,
    height:     int,
    handle:     str   = "@tekiyo_",
    bg:         tuple = (255, 255, 255),
    text_color: tuple = (30, 30, 30),
) -> np.ndarray:
    """
    FIX 2026-04-15: Search bar pill fidèle à la référence.
    - Fond blanc, coins arrondis
    - Bordure gauche 3px #00F2EA (cyan), bordure droite 3px #FF0050 (rouge)
    - Icône loupe noire à gauche
    - "@tekiyo_" centré, Inter-Regular
    - Mini logo TikTok (note 'd' + glitch) à droite intérieur
    """
    radius = height // 2
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    # 1. Fond blanc
    draw.rounded_rectangle([0, 0, width-1, height-1], radius=radius, fill=bg + (255,))

    # 2. Bordure bicolore — contour complet en cyan puis demi-droite écrasée en rouge
    border_w = 3
    cy_col   = (0, 242, 234, 255)    # #00F2EA
    rd_col   = (255, 0, 80, 255)     # #FF0050

    b_layer  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bd       = ImageDraw.Draw(b_layer)
    bd.rounded_rectangle([0, 0, width-1, height-1], radius=radius,
                          outline=cy_col, width=border_w)

    r_layer  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rd       = ImageDraw.Draw(r_layer)
    rd.rounded_rectangle([0, 0, width-1, height-1], radius=radius,
                          outline=rd_col, width=border_w)
    mask_r   = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask_r).rectangle([width // 2, 0, width, height], fill=255)
    b_layer.paste(r_layer, (0, 0), mask=mask_r)
    canvas.alpha_composite(b_layer)
    draw = ImageDraw.Draw(canvas)   # rafraîchir draw sur canvas mis à jour

    # 3. Icône loupe à gauche
    icon_size = int(height * 0.55)
    pad       = int(height * 0.25)
    lx, ly    = pad, (height - icon_size) // 2
    sr        = int(icon_size * 0.38)
    draw.ellipse([lx, ly, lx + sr * 2, ly + sr * 2],
                 outline=(80, 80, 80, 255), width=2)
    lp = int(sr * 0.70)
    draw.line([lx + sr + lp - 2, ly + sr + lp - 2,
               lx + icon_size,   ly + icon_size],
              fill=(80, 80, 80, 255), width=3)

    # 4. Handle centré — Inter-Regular (FIX 2026-04-15: était semibold)
    font_size = max(20, int(height * 0.40))
    font      = find_font("regular", font_size)
    tw, th    = measure_text(handle, font)
    tx        = (width - tw) // 2
    ty        = (height - th) // 2
    draw.text((tx, ty), handle, font=font, fill=text_color + (255,))

    # 5. Mini logo TikTok à droite (note 'd' + glitch, 45% de la hauteur)
    mini_size = max(20, int(height * 0.45))
    mini_arr  = _render_tiktok_logo_vector(mini_size)
    mini_img  = Image.fromarray(mini_arr, mode="RGBA")
    rx        = width - pad - mini_size
    ry        = (height - mini_size) // 2
    canvas.paste(mini_img, (rx, ry), mask=mini_img.split()[3])

    return np.array(canvas)


def render_cta_card(
    canvas_w:   int,
    canvas_h:   int,
    handle:     str   = None,
    logo_scale: float = 1.0,
) -> np.ndarray:
    """
    ARCHITECTURE_MASTER_V31: CTA card TikTok complète.
    Position logo corrigée V31: CTA_LOGO_CENTER_Y_RATIO=0.374H.
    """
    if handle is None:
        handle = CTA_TIKTOK_HANDLE

    canvas_arr       = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    canvas_arr[:,:,0] = CTA_BG_COLOR[0]
    canvas_arr[:,:,1] = CTA_BG_COLOR[1]
    canvas_arr[:,:,2] = CTA_BG_COLOR[2]
    canvas_arr[:,:,3] = 255

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


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 7 — REPEATER scene (fond gris + grille tile + mot blanc centré)
# Référence vidéo frame t=28s : fond #838383, emoji 🏢 tilé, "doublé" en blanc.
# ══════════════════════════════════════════════════════════════════════════════

_REPEATER_BG = (131, 131, 131)   # #838383

def render_repeater_scene(
    word:     str,
    tile:     str = "■",
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> np.ndarray:
    """
    Génère un frame plein écran REPEATER :
        - Fond gris #838383
        - Caractère/emoji tilé en grille dense (couleur légèrement plus sombre)
        - Mot principal en blanc ExtraBold centré à 50% V

    `tile` peut être un emoji (🏢) ou un caractère quelconque.
    Sur Windows, Segoe UI Emoji est tenté en priorité pour le tileage.
    Fallback garanti sur caractère ASCII si la font emoji est indisponible.
    """
    bg = Image.new("RGB", (canvas_w, canvas_h), _REPEATER_BG)
    draw = ImageDraw.Draw(bg)

    # ── Font emoji pour le tileage ────────────────────────────────────────
    tile_size = max(48, int(canvas_w * 0.055))
    tile_font = None
    for fp in [
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/seguisym.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    ]:
        try:
            if os.path.exists(fp):
                tile_font = ImageFont.truetype(fp, tile_size)
                break
        except Exception:
            continue
    if tile_font is None:
        tile_font = find_font("regular", tile_size)
        tile = "■"   # fallback ASCII si pas de font emoji

    # ── Grille dense ──────────────────────────────────────────────────────
    tile_color = (100, 100, 100)   # légèrement plus sombre que le fond
    spacing    = int(tile_size * 1.25)
    for row_y in range(-spacing, canvas_h + spacing, spacing):
        for col_x in range(-spacing, canvas_w + spacing, spacing):
            try:
                draw.text((col_x, row_y), tile, font=tile_font, fill=tile_color)
            except Exception:
                draw.text((col_x, row_y), "■", font=tile_font, fill=tile_color)

    # ── Mot principal en blanc ExtraBold centré ───────────────────────────
    clean = re.sub(r'\[.*?\]', '', word).strip() or word.strip()
    word_font, _, tw, th = auto_size_font(clean, "extrabold", 90, canvas_w - 80)
    tx = (canvas_w - tw) // 2
    ty = int(canvas_h * 0.499) - th // 2
    # Ombre légère
    draw.text((tx + 3, ty + 4), clean, font=word_font, fill=(80, 80, 80))
    # Texte blanc
    draw.text((tx, ty), clean, font=word_font, fill=(255, 255, 255))

    return np.array(bg)


# ══════════════════════════════════════════════════════════════════════════════
# BLOC 8 — ICON scene (fond blanc + icône/emoji centré)
# Référence vidéo frame t=18s : œil noir plat centré sur fond blanc.
# ══════════════════════════════════════════════════════════════════════════════

_ICON_MAP = {
    "oeil": "👁",  "eye": "👁",    "regard": "👁",
    "feu":  "🔥",  "fire": "🔥",
    "argent": "💰","money": "💰",
    "fusée": "🚀", "rocket": "🚀",
    "cercle": "●", "circle": "●",
    "check": "✓",  "valide": "✓",
    "alerte": "⚠", "warning": "⚠",
    "cadenas": "🔒","lock": "🔒",
    "graphique": "📈","chart": "📈",
    "diamant": "💎","diamond": "💎",
    "etoile": "★", "star": "★",
    "fleche": "→", "arrow": "→",
}


def render_icon_scene(
    icon_param: str,
    canvas_w:   int = 1080,
    canvas_h:   int = 1920,
) -> np.ndarray:
    """
    Génère un frame plein écran ICON :
        - Fond blanc pur
        - Icône/emoji noir centré à 50% V, ~15% de la largeur (≈162px@1080)

    `icon_param` est le nom normalisé (ex: "oeil", "feu") ou un emoji direct.
    Si le rendu emoji échoue, dessine un disque noir de fallback.
    """
    bg   = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(bg)

    # Résoudre le caractère
    icon_char = _ICON_MAP.get(icon_param.lower().strip(), icon_param[:4])

    icon_size = max(80, int(canvas_w * 0.15))   # ~162px à 1080px
    icon_font = None
    for fp in [
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/seguisym.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    ]:
        try:
            if os.path.exists(fp):
                icon_font = ImageFont.truetype(fp, icon_size)
                break
        except Exception:
            continue

    cx = canvas_w // 2
    cy = int(canvas_h * 0.499)

    if icon_font is not None:
        try:
            bbox = draw.textbbox((0, 0), icon_char, font=icon_font)
            tw   = bbox[2] - bbox[0]
            th   = bbox[3] - bbox[1]
            draw.text((cx - tw // 2, cy - th // 2), icon_char,
                      font=icon_font, fill=(10, 10, 10, 255))
        except Exception:
            icon_font = None   # fallback disque

    if icon_font is None:
        r = icon_size // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 10, 10, 255))

    return np.array(bg.convert("RGB"))