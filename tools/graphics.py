# -*- coding: utf-8 -*-
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from typing import Optional, Tuple
from pathlib import Path

from .config import ASSET_DICT, ASSET_DIR, TEXT_RGB

def find_font(weight: str = "regular", size: int = 75) -> ImageFont.FreeTypeFont:
    candidates_map = {
        "regular": [
            "Inter-Regular.ttf", "Inter_Regular.ttf",
            "Montserrat-Regular.ttf", "Montserrat-Medium.ttf",
            "Poppins-Regular.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ],
        "bold": [
            "Inter-Bold.ttf", "Inter_Bold.ttf", "Inter-SemiBold.ttf",
            "Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf",
            "Poppins-Bold.ttf", "C:\\Windows\\Fonts\\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "extrabold": [
            "Inter-ExtraBold.ttf", "Inter-Black.ttf",
            "Montserrat-ExtraBold.ttf", "Montserrat-Black.ttf",
            "Poppins-Black.ttf", "C:\\Windows\\Fonts\\impact.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
        "black": [
            "Inter-Black.ttf", "Montserrat-Black.ttf",
            "Poppins-Black.ttf", "BebasNeue-Regular.ttf",
            "C:\\Windows\\Fonts\\impact.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
    }
    candidates = candidates_map.get(weight, candidates_map["regular"])
    for fp in candidates:
        if fp and os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    print(f"⚠️  Police '{weight}' size={size} introuvable. Fallback PIL.")
    return ImageFont.load_default()

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

def render_phrase_rgba(text: str, fs: int, weight: str = "regular", color: tuple = TEXT_RGB, max_w: int = 920, inverted: bool = False) -> np.ndarray:
    shadow_col = (200, 200, 200) if inverted else (0, 0, 0)
    font = find_font(weight=weight, size=fs)
    dummy = Image.new("RGBA", (1, 1))
    d     = ImageDraw.Draw(dummy)

    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * int(fs * 0.6), fs

    while tw > max_w and fs > 20:
        fs   = max(20, int(fs * (max_w / max(tw, 1))))
        font = find_font(weight=weight, size=fs)
        try:
            bbox = d.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * int(fs * 0.6), fs
        break

    pad_x, pad_y = 50, 50
    cw = tw + pad_x * 2
    ch = th + pad_y * 2

    shadow_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow_img)
    ds.text((pad_x - bbox[0], pad_y - bbox[1] + 6), text, font=font, fill=shadow_col + (13,))
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=20))

    text_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    dt = ImageDraw.Draw(text_img)
    dt.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=color + (255,))

    return np.array(Image.alpha_composite(shadow_img, text_img))