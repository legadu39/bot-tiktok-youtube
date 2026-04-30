# -*- coding: utf-8 -*-
"""
tests/unit/test_asset_rembg.py
Pipeline assets rembg — 3 tests obligatoires (spec DA).

    - test_rembg_output_has_alpha   : image retournée en mode RGBA
    - test_background_is_white      : coins du canvas = #FFFFFF
    - test_no_pexels_call           : aucun appel vers api.pexels.com

rembg est mocké via sys.modules pour éviter l'import de onnxruntime (non requis
en CI/CD). Le module factice expose rembg.remove() comme attribut callable.
"""
import io
import json
import os
import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest
from PIL import Image

# ── Injection du faux module rembg AVANT tout import de asset_vault ──────────
# rembg n'est pas installé en CI — on crée un module factice pour que
# `import rembg` dans fetch_and_cache réussisse.
_fake_rembg = types.ModuleType("rembg")
_fake_rembg.remove = MagicMock(return_value=b"")  # sera surchargé dans chaque test
sys.modules.setdefault("rembg", _fake_rembg)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_rgba_png_bytes(w: int = 80, h: int = 60, color=(255, 0, 0, 255)) -> bytes:
    """Génère un PNG RGBA solide (carré rouge par défaut) en bytes."""
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _make_rgb_jpeg_bytes(w: int = 80, h: int = 60) -> bytes:
    """Génère un JPEG RGB minimal en bytes (image source brute)."""
    img = Image.new("RGB", (w, h), (180, 120, 60))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _make_vault(tmp_path: Path):
    """Instancie AssetVault avec un répertoire temporaire isolé."""
    with patch("tools.asset_vault.resolve_path", side_effect=lambda p: tmp_path / p), \
         patch("tools.asset_vault.CONFIG", {"directories": {}}):
        from tools.asset_vault import AssetVault
        vault = AssetVault.__new__(AssetVault)
        vault.assets_dir   = tmp_path
        vault.downloads_dir = tmp_path / "downloads"
        vault.sfx_dir      = str(tmp_path / "sfx")
        vault.index_path   = tmp_path / "vault_index.json"
        vault.index        = {"assets": []}
        vault.sfx_cache    = {"pop": [], "whoosh": [], "success": [], "click": []}
        vault.assets_dir.mkdir(parents=True, exist_ok=True)
        vault.downloads_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "sfx").mkdir(parents=True, exist_ok=True)
        return vault


# ──────────────────────────────────────────────────────────────────────────────
# test_rembg_output_has_alpha
# ──────────────────────────────────────────────────────────────────────────────

def test_rembg_output_has_alpha(tmp_path):
    """
    L'image retournée par fetch_and_cache doit être sauvegardée en mode RGBA.
    rembg.remove est mocké pour éviter l'appel au modèle U2Net.
    """
    vault = _make_vault(tmp_path)

    source_bytes = _make_rgb_jpeg_bytes()
    rembg_output = _make_rgba_png_bytes(color=(255, 0, 0, 255))  # sujet rouge opaque

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = source_bytes

    _fake_rembg.remove = MagicMock(return_value=rembg_output)
    with patch("requests.get", return_value=fake_resp):
        result = vault.fetch_and_cache("http://example.com/product.jpg")

    assert result is not None, "fetch_and_cache doit retourner un chemin"
    assert result.endswith(".png"), "Le fichier de sortie doit être un PNG"

    saved = Image.open(result)
    assert saved.mode == "RGBA", f"Mode attendu RGBA, obtenu {saved.mode}"


# ──────────────────────────────────────────────────────────────────────────────
# test_background_is_white
# ──────────────────────────────────────────────────────────────────────────────

def test_background_is_white(tmp_path):
    """
    Les quatre coins du canvas composite doivent être #FFFFFF (255,255,255,255).
    Le sujet rembg est un rectangle 40×30 opaque placé au centre —
    les coins du canvas 810×864 restent blancs.
    """
    vault = _make_vault(tmp_path)

    source_bytes = _make_rgb_jpeg_bytes()
    # Sujet petit (40×30) → les coins du canvas 810×864 seront intacts (#FFFFFF)
    rembg_output = _make_rgba_png_bytes(w=40, h=30, color=(0, 0, 255, 255))

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = source_bytes

    _fake_rembg.remove = MagicMock(return_value=rembg_output)
    with patch("requests.get", return_value=fake_resp):
        result = vault.fetch_and_cache("http://example.com/product2.jpg")

    assert result is not None

    img = Image.open(result)
    assert img.mode == "RGBA"
    arr = np.array(img)
    h, w = arr.shape[:2]
    WHITE = (255, 255, 255, 255)

    corners = [
        ("(0,0)",   tuple(arr[0,  0,  :].tolist())),
        ("(0,-1)",  tuple(arr[0,  -1, :].tolist())),
        ("(-1,0)",  tuple(arr[-1, 0,  :].tolist())),
        ("(-1,-1)", tuple(arr[-1, -1, :].tolist())),
    ]
    for label, pixel in corners:
        assert pixel == WHITE, (
            f"Coin {label} attendu {WHITE}, obtenu {pixel} — fond non blanc"
        )


# ──────────────────────────────────────────────────────────────────────────────
# test_no_pexels_call
# ──────────────────────────────────────────────────────────────────────────────

def test_no_pexels_call(tmp_path):
    """
    Aucun appel HTTP vers api.pexels.com ne doit être effectué.
    Vérifie que requests.get n'est jamais appelé avec une URL Pexels.
    """
    vault = _make_vault(tmp_path)

    source_bytes = _make_rgb_jpeg_bytes()
    rembg_output = _make_rgba_png_bytes()

    captured_urls = []

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.content = source_bytes
        return resp

    _fake_rembg.remove = MagicMock(return_value=rembg_output)
    with patch("requests.get", side_effect=fake_get):
        vault.fetch_and_cache("http://example.com/product3.jpg")

    # Aucune URL appelée ne doit contenir "pexels.com"
    pexels_calls = [u for u in captured_urls if "pexels.com" in u]
    assert len(pexels_calls) == 0, (
        f"Appels Pexels détectés (interdits) : {pexels_calls}"
    )

    # L'unique appel doit être vers l'URL fournie directement
    assert len(captured_urls) == 1, f"Attendu 1 appel HTTP, obtenu {len(captured_urls)}"
    assert captured_urls[0] == "http://example.com/product3.jpg"
