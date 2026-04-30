# -*- coding: utf-8 -*-
"""
DA Premium — tests outro TikTok pixel-perfect.

Couvre :
    - render_cta_card() : génère sans crasher, dimensions correctes
    - Fond #0D1019 exact
    - Barre de recherche fond #1A1D27, radius=8px, zéro bordure parasite
    - Handle @tekiyo_ centré, blanc #FFFFFF
    - Logo placeholder : 120×120 entièrement transparent
"""
import numpy as np
import pytest


VID_W, VID_H = 1080, 1920
HANDLE = "@tekiyo_"

# Couleurs cibles (spec DA Premium)
BG_COLOR     = (13, 16, 25)    # #0D1019
PILL_COLOR   = (26, 29, 39)    # #1A1D27
WHITE        = (255, 255, 255)


# ──────────────────────────────────────────────────────────────────────────────
# 1. render_cta_card — smoke test + dimensions
# ──────────────────────────────────────────────────────────────────────────────

class TestCtaCardSmoke:
    def test_renders_without_crash(self):
        from tools.graphics import render_cta_card
        arr = render_cta_card(VID_W, VID_H, handle=HANDLE)
        assert arr is not None

    def test_output_shape(self):
        from tools.graphics import render_cta_card
        arr = render_cta_card(VID_W, VID_H, handle=HANDLE)
        assert arr.shape[:2] == (VID_H, VID_W)

    def test_output_rgb_or_rgba(self):
        from tools.graphics import render_cta_card
        arr = render_cta_card(VID_W, VID_H, handle=HANDLE)
        assert arr.ndim == 3 and arr.shape[2] in (3, 4)


# ──────────────────────────────────────────────────────────────────────────────
# 2. Couleur de fond #0D1019
# ──────────────────────────────────────────────────────────────────────────────

class TestCtaBackground:
    def _sample_corners(self, arr):
        """Retourne la couleur RGB dans les 4 coins (zone sûre loin de la pill)."""
        # On échantillonne dans les 8 premiers % de hauteur (coin haut)
        samples = [
            arr[20, 20, :3],
            arr[20, VID_W - 20, :3],
        ]
        return [tuple(s.tolist()) for s in samples]

    def test_bg_color_top_corners(self):
        from tools.graphics import render_cta_card
        arr = render_cta_card(VID_W, VID_H, handle=HANDLE)
        for pixel in self._sample_corners(arr):
            assert pixel == BG_COLOR, (
                f"Fond attendu {BG_COLOR}, obtenu {pixel} — vérifier CTA_BG_COLOR"
            )

    def test_bg_is_not_pure_black(self):
        from tools.graphics import render_cta_card
        arr = render_cta_card(VID_W, VID_H, handle=HANDLE)
        top_strip = arr[:50, :, :3]
        assert tuple(top_strip[10, 10].tolist()) != (0, 0, 0), (
            "Fond ne doit pas être noir pur — attendu #0D1019"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Barre de recherche — fond #1A1D27, pas de rouge/cyan
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchPill:
    def _get_pill_arr(self):
        from tools.graphics import _render_search_pill
        from tools.config import CTA_SEARCH_WIDTH_RATIO, CTA_SEARCH_HEIGHT_RATIO
        w = int(VID_W * CTA_SEARCH_WIDTH_RATIO)
        h = max(40, int(VID_H * CTA_SEARCH_HEIGHT_RATIO))
        return _render_search_pill(w, h, HANDLE)

    def test_pill_renders_without_crash(self):
        arr = self._get_pill_arr()
        assert arr is not None

    def test_pill_bg_color_center(self):
        """Le centre de la pill doit être #1A1D27."""
        arr = self._get_pill_arr()
        h, w = arr.shape[:2]
        cx, cy = w // 2, h // 2
        pixel = tuple(arr[cy, cx, :3].tolist())
        assert pixel == PILL_COLOR, (
            f"Centre pill attendu {PILL_COLOR}, obtenu {pixel}"
        )

    def test_pill_no_cyan_border(self):
        """Zéro pixel cyan #00F2EA sur les bords."""
        arr = self._get_pill_arr()
        h, w = arr.shape[:2]
        # Bord gauche (colonne 0..2)
        left_edge = arr[:, :3, :3]
        cyan = (0, 242, 234)
        has_cyan = any(
            tuple(left_edge[y, x].tolist()) == cyan
            for y in range(h) for x in range(3)
        )
        assert not has_cyan, "Bordure cyan #00F2EA détectée — ne doit pas exister"

    def test_pill_no_red_border(self):
        """Zéro pixel rouge #FF0050 sur les bords."""
        arr = self._get_pill_arr()
        h, w = arr.shape[:2]
        right_edge = arr[:, -3:, :3]
        red = (255, 0, 80)
        has_red = any(
            tuple(right_edge[y, x].tolist()) == red
            for y in range(h) for x in range(3)
        )
        assert not has_red, "Bordure rouge #FF0050 détectée — ne doit pas exister"

    def test_pill_has_white_pixels(self):
        """Le handle blanc doit produire des pixels blancs (ou quasi-blancs ≥240)."""
        arr = self._get_pill_arr()
        rgb = arr[:, :, :3]
        white_pixels = np.all(rgb >= 240, axis=2)
        assert white_pixels.any(), "Aucun pixel blanc trouvé — handle non rendu"

    def test_pill_radius_8_corners_transparent(self):
        """Avec radius=8, les coins (1px) doivent être transparents."""
        arr = self._get_pill_arr()
        if arr.shape[2] < 4:
            pytest.skip("Pas de canal alpha")
        # Pixel 0,0 doit être transparent (coin arrondi)
        assert arr[0, 0, 3] == 0, f"Coin haut-gauche non transparent (alpha={arr[0,0,3]})"
        assert arr[-1, -1, 3] == 0, f"Coin bas-droite non transparent (alpha={arr[-1,-1,3]})"

    def test_pill_y_position_55pct(self):
        """La pill doit être centrée à ~55% de la hauteur."""
        from tools.config import CTA_SEARCH_CENTER_Y_RATIO
        assert abs(CTA_SEARCH_CENTER_Y_RATIO - 0.55) < 0.01, (
            f"CTA_SEARCH_CENTER_Y_RATIO={CTA_SEARCH_CENTER_Y_RATIO} != 0.55"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Logo placeholder — 120×120 entièrement transparent
# ──────────────────────────────────────────────────────────────────────────────

class TestLogoPlaceholder:
    def test_placeholder_shape(self):
        from tools.graphics import _render_tiktok_logo_vector
        arr = _render_tiktok_logo_vector(216)   # taille appelée dans render_cta_card
        assert arr.shape == (120, 120, 4), (
            f"Placeholder attendu (120,120,4), obtenu {arr.shape}"
        )

    def test_placeholder_fully_transparent(self):
        from tools.graphics import _render_tiktok_logo_vector
        arr = _render_tiktok_logo_vector(216)
        assert arr[:, :, 3].max() == 0, (
            "Le placeholder logo doit être entièrement transparent (alpha=0 partout)"
        )

    def test_no_glitch_colors(self):
        """Aucun pixel cyan #00F2EA ni rouge #FF0050 dans le placeholder."""
        from tools.graphics import _render_tiktok_logo_vector
        arr = _render_tiktok_logo_vector(120)
        rgb = arr[:, :, :3]
        cyan_mask = np.all(rgb == [0, 242, 234], axis=2)
        red_mask  = np.all(rgb == [255, 0, 80],  axis=2)
        assert not cyan_mask.any(), "Pixel cyan glitch détecté dans le placeholder"
        assert not red_mask.any(),  "Pixel rouge glitch détecté dans le placeholder"
