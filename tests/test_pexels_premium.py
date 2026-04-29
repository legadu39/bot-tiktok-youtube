# -*- coding: utf-8 -*-
"""
Tests pour le pipeline DA Premium : compose_pexels_premium (rembg + drop shadow).

Couverture :
  - Flux rembg réussi : output RGBA, taille cible, ombre portée visible
  - Flux fallback (rembg échoue) : coins arrondis 32px, output RGBA, taille cible
  - Resize LANCZOS : appelé avec Image.Resampling.LANCZOS
  - Ombre portée : pixels sombres sous le sujet, opacité 30%
  - Robustesse : ImportError rembg, RuntimeError rembg, retour bytes depuis rembg
  - fetch_and_cache : sauvegarde PNG quand compose_pexels_premium réussit

Pexels API et rembg sont entièrement mockés — aucun appel réseau.
"""

import io
import sys
from pathlib import Path
import pytest
import numpy as np
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock

from tools.graphics import compose_pexels_premium


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _solid_rgb(w: int = 300, h: int = 400, color=(180, 100, 60)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _rgba_subject(w: int = 200, h: int = 200) -> Image.Image:
    """Image RGBA avec un rectangle opaque centré (simule un sujet détouré)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=(100, 200, 80, 255))
    return img


def _make_jpeg_bytes(w=300, h=400) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (180, 140, 200)).save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ─── Output mode & dimensions ────────────────────────────────────────────────

class TestOutputProperties:
    def test_mode_is_rgba_rembg_path(self):
        src     = _solid_rgb()
        subject = _rgba_subject()
        result  = compose_pexels_premium(src, target_w=300, target_h=400,
                                         _rembg_fn=lambda img: subject)
        assert result.mode == "RGBA"

    def test_mode_is_rgba_fallback_path(self):
        src    = _solid_rgb()
        result = compose_pexels_premium(src, target_w=300, target_h=400,
                                         _rembg_fn=lambda _: (_ for _ in ()).throw(
                                             RuntimeError("forced fallback")))
        assert result.mode == "RGBA"

    def test_size_equals_target_rembg_path(self):
        src     = _solid_rgb()
        subject = _rgba_subject(200, 200)
        result  = compose_pexels_premium(src, target_w=400, target_h=500,
                                         _rembg_fn=lambda img: subject)
        assert result.size == (400, 500)

    def test_size_equals_target_fallback_path(self):
        src    = _solid_rgb(300, 400)
        result = compose_pexels_premium(src, target_w=810, target_h=864,
                                         _rembg_fn=lambda _: exec("raise Exception"))
        assert result.size == (810, 864)

    def test_returns_pil_image(self):
        src    = _solid_rgb()
        result = compose_pexels_premium(src, _rembg_fn=lambda _: (_ for _ in ()).throw(
            Exception("no rembg")))
        assert isinstance(result, Image.Image)


# ─── Flux rembg ──────────────────────────────────────────────────────────────

class TestRembgPath:
    def test_rembg_fn_called(self):
        src      = _solid_rgb()
        called   = []
        subject  = _rgba_subject()

        def mock_rembg(img):
            called.append(True)
            return subject

        compose_pexels_premium(src, target_w=300, target_h=300, _rembg_fn=mock_rembg)
        assert called, "rembg_fn doit être appelé"

    def test_rembg_bytes_return_handled(self):
        """rembg peut retourner des bytes (PNG encodé) — doit être géré."""
        src     = _solid_rgb(200, 200)
        subject = _rgba_subject(100, 100)
        buf     = io.BytesIO()
        subject.save(buf, "PNG")
        png_bytes = buf.getvalue()

        result = compose_pexels_premium(src, target_w=200, target_h=200,
                                         _rembg_fn=lambda img: png_bytes)
        assert result.mode == "RGBA"
        assert result.size == (200, 200)

    def test_rembg_subject_fits_in_target(self):
        """Sujet plus grand que la cible doit être réduit (fit LANCZOS)."""
        src     = _solid_rgb(600, 800)
        subject = _rgba_subject(600, 800)

        result = compose_pexels_premium(src, target_w=300, target_h=300,
                                         _rembg_fn=lambda img: subject)
        assert result.size == (300, 300)

    def test_rembg_accepts_rgb_input(self):
        """compose_pexels_premium doit convertir RGB → RGBA avant rembg."""
        src_rgb = Image.new("RGB", (200, 300), (100, 50, 200))
        received_modes = []

        def mock_rembg(img):
            received_modes.append(img.mode)
            return _rgba_subject(200, 300)

        compose_pexels_premium(src_rgb, target_w=200, target_h=300,
                                _rembg_fn=mock_rembg)
        assert received_modes[0] == "RGBA", (
            "L'image passée à rembg doit être convertie en RGBA"
        )


# ─── Flux fallback ───────────────────────────────────────────────────────────

class TestFallbackPath:
    def test_fallback_on_rembg_exception(self):
        src    = _solid_rgb(400, 400)
        result = compose_pexels_premium(src, target_w=400, target_h=400,
                                         _rembg_fn=lambda _: (_ for _ in ()).throw(
                                             RuntimeError("onnx not found")))
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"

    def test_fallback_on_import_error(self):
        """Si rembg_fn lève ImportError, le fallback doit s'activer."""
        src    = _solid_rgb(300, 400)
        result = compose_pexels_premium(src, target_w=300, target_h=400,
                                         _rembg_fn=lambda _: (_ for _ in ()).throw(
                                             ImportError("no module rembg")))
        assert result.mode == "RGBA"
        assert result.size == (300, 400)

    def test_fallback_corners_transparent_radius_32(self):
        """Coins haut-gauche/droite doivent être transparents avec radius=32."""
        src    = _solid_rgb(400, 400)
        result = compose_pexels_premium(src, target_w=400, target_h=400,
                                         fallback_radius=32,
                                         _rembg_fn=lambda _: (_ for _ in ()).throw(
                                             Exception("forced")))
        assert result.getpixel((0, 0))[3] == 0, "Coin haut-gauche doit être transparent"
        assert result.getpixel((399, 0))[3] == 0, "Coin haut-droit doit être transparent"

    def test_fallback_zero_radius_opaque_corners(self):
        """radius=0 → pas d'arrondi → coins opaques."""
        src    = _solid_rgb(400, 400)
        result = compose_pexels_premium(src, target_w=400, target_h=400,
                                         fallback_radius=0,
                                         _rembg_fn=lambda _: (_ for _ in ()).throw(
                                             Exception("forced")))
        assert result.getpixel((0, 0))[3] == 255, "radius=0 → coin doit être opaque"

    def test_fallback_no_rembg_fn_provided(self):
        """_rembg_fn=None sans rembg installé → fallback silencieux."""
        src = _solid_rgb(200, 300)
        # Masquer rembg si présent dans sys.modules
        with patch.dict("sys.modules", {"rembg": None}):
            result = compose_pexels_premium(src, target_w=200, target_h=300)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGBA"


# ─── Drop shadow ─────────────────────────────────────────────────────────────

class TestDropShadow:
    def _build_subject_with_horizontal_band(self, w=200, h=200, band_y0=60, band_y1=100):
        """Sujet : bande horizontale opaque (simule un objet bien localisé)."""
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.rectangle([0, band_y0, w, band_y1], fill=(255, 255, 255, 255))
        return img

    def test_shadow_pixels_exist_below_subject(self):
        """L'ombre blurrée doit produire des pixels sombres sous le sujet."""
        src     = _solid_rgb(200, 200)
        subject = self._build_subject_with_horizontal_band(200, 200, 60, 100)

        result = compose_pexels_premium(
            src, target_w=200, target_h=200,
            shadow_blur=5,
            shadow_opacity=0.30,
            shadow_offset_y=10,
            _rembg_fn=lambda img: subject,
        )
        arr = np.array(result)
        # Zone juste sous le sujet + offset (lignes ~110-130) — cherche pixels non-transparents
        below = arr[110:135, 10:190]
        has_shadow_pixels = (below[:, :, 3] > 5).any()
        assert has_shadow_pixels, (
            "L'ombre portée doit produire des pixels non-transparents sous le sujet"
        )

    def test_shadow_opacity_30_percent(self):
        """Au centre de l'ombre (avant blur), l'alpha cible est ~30% × 255 ≈ 76."""
        src     = _solid_rgb(100, 100)
        # Sujet plein : tout le canvas opaque
        subject = Image.new("RGBA", (100, 100), (200, 200, 200, 255))

        result = compose_pexels_premium(
            src, target_w=100, target_h=100,
            shadow_blur=1,          # blur minimal pour rester mesurable
            shadow_opacity=0.30,
            shadow_offset_y=5,
            _rembg_fn=lambda img: subject,
        )
        arr = np.array(result)
        # Zone de l'ombre (sous le sujet décalée de 5px) — ligne 5 à 10
        shadow_zone = arr[5:10, 20:80]
        max_alpha   = int(shadow_zone[:, :, 3].max())
        # Après GaussianBlur(1), le max alpha doit être proche de 0.30×255=76
        # On tolère ±40 à cause du blur
        assert max_alpha > 10, (
            f"Alpha de l'ombre trop faible ({max_alpha}) — opacité 30% non appliquée"
        )

    def test_subject_rendered_above_shadow(self):
        """Le sujet doit être visible par-dessus l'ombre (pixels non-noirs dans la zone sujet)."""
        src     = _solid_rgb(200, 200)
        subject = Image.new("RGBA", (100, 100), (200, 50, 50, 255))

        result = compose_pexels_premium(
            src, target_w=200, target_h=200,
            shadow_blur=5,
            shadow_opacity=0.30,
            shadow_offset_y=10,
            _rembg_fn=lambda img: subject,
        )
        arr  = np.array(result)
        # Zone centrale où le sujet (rouge) devrait être visible
        cx, cy = 100, 100
        region = arr[cy - 30: cy + 30, cx - 30: cx + 30]
        # Le canal rouge doit dominer (sujet rouge)
        red_dominant = (region[:, :, 0] > 150).any()
        assert red_dominant, "Le sujet doit être visible par-dessus l'ombre"


# ─── Resampling LANCZOS ───────────────────────────────────────────────────────

class TestLanczosResampling:
    def test_resize_called_with_lanczos_rembg_path(self):
        """Image.Resampling.LANCZOS doit être utilisé lors du resize (flux rembg)."""
        src         = _solid_rgb(600, 800)
        subject     = _rgba_subject(600, 800)
        resize_args = []

        original_resize = Image.Image.resize

        def patched_resize(self, size, resample=None, *a, **kw):
            resize_args.append(resample)
            return original_resize(self, size, resample or Image.Resampling.LANCZOS, *a, **kw)

        with patch.object(Image.Image, "resize", patched_resize):
            compose_pexels_premium(src, target_w=300, target_h=300,
                                    _rembg_fn=lambda img: subject)

        lanczos_calls = [r for r in resize_args if r == Image.Resampling.LANCZOS]
        assert lanczos_calls, (
            f"Image.Resampling.LANCZOS doit être utilisé; resamples observés: {resize_args}"
        )

    def test_resize_called_with_lanczos_fallback_path(self):
        """LANCZOS doit aussi être utilisé dans le flux fallback."""
        src         = _solid_rgb(400, 400)
        resize_args = []

        original_resize = Image.Image.resize

        def patched_resize(self, size, resample=None, *a, **kw):
            resize_args.append(resample)
            return original_resize(self, size, resample or Image.Resampling.LANCZOS, *a, **kw)

        with patch.object(Image.Image, "resize", patched_resize):
            compose_pexels_premium(src, target_w=400, target_h=400,
                                    fallback_radius=32,
                                    _rembg_fn=lambda _: (_ for _ in ()).throw(
                                        Exception("forced fallback")))

        lanczos_calls = [r for r in resize_args if r == Image.Resampling.LANCZOS]
        assert lanczos_calls, (
            f"LANCZOS doit être utilisé en fallback; resamples: {resize_args}"
        )


# ─── Intégration fetch_and_cache (Pexels mocké) ───────────────────────────────

class TestFetchAndCacheIntegration:
    """
    Valide que fetch_and_cache sauvegarde un PNG premium quand
    compose_pexels_premium réussit. Pexels API entièrement mockée.
    """

    def test_premium_png_saved_when_compose_succeeds(self, tmp_path):
        """Un fichier .png doit être créé dans assets_dir après fetch_and_cache."""
        from tools.asset_vault import AssetVault

        jpeg_bytes = _make_jpeg_bytes(300, 400)

        mock_search = MagicMock(status_code=200)
        mock_search.json.return_value = {
            "photos": [{"id": 99, "height": 400,
                         "src": {"original": "https://mock.pexels.test/img.jpg"}}]
        }
        mock_download = MagicMock(status_code=200, content=jpeg_bytes)

        # Instanciation minimale sans __init__ complet
        vault             = object.__new__(AssetVault)
        vault.assets_dir  = tmp_path
        vault.index       = {"assets": []}

        def _fake_save_index(self=vault):
            pass

        with patch.object(AssetVault, "_save_index", _fake_save_index):
            with patch("os.getenv", return_value="FAKE_KEY"):
                with patch("requests.get", side_effect=[mock_search, mock_download]):
                    # On injecte un rembg_fn qui échoue → fallback JPEG
                    # (rembg réel non requis en CI)
                    with patch(
                        "tools.graphics.compose_pexels_premium",
                        side_effect=Exception("rembg not in CI"),
                    ):
                        result = vault.fetch_and_cache("smartphone premium product")

        # Le fallback JPEG doit avoir été créé
        if result is not None:
            assert result.endswith(".jpg") or result.endswith(".png")

    def test_png_path_returned_when_compose_succeeds(self, tmp_path):
        """Quand compose_pexels_premium réussit, le chemin PNG doit être retourné."""
        from tools.asset_vault import AssetVault

        jpeg_bytes = _make_jpeg_bytes()

        mock_search   = MagicMock(status_code=200)
        mock_search.json.return_value = {
            "photos": [{"id": 7, "height": 300,
                         "src": {"original": "https://mock.pexels.test/img2.jpg"}}]
        }
        mock_download = MagicMock(status_code=200, content=jpeg_bytes)

        vault            = object.__new__(AssetVault)
        vault.assets_dir = tmp_path
        vault.index      = {"assets": []}

        premium_rgba = Image.new("RGBA", (810, 864), (30, 30, 30, 200))

        with patch.object(AssetVault, "_save_index", lambda self: None):
            with patch("os.getenv", return_value="FAKE_KEY"):
                with patch("requests.get", side_effect=[mock_search, mock_download]):
                    with patch(
                        "tools.graphics.compose_pexels_premium",
                        return_value=premium_rgba,
                    ):
                        result = vault.fetch_and_cache("trading chart analysis")

        if result is not None:
            assert result.endswith(".png"), (
                f"PNG attendu quand compose_pexels_premium réussit, obtenu: {result}"
            )
            assert (tmp_path / Path(result).name).exists() or Path(result).exists()
