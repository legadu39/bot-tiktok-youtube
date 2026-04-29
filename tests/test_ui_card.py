# -*- coding: utf-8 -*-
"""
Tests pour tools/graphics.py — draw_ui_card (DA Premium).

Valide les dimensions dynamiques de la bounding box :
    box_width  = text_width  + padding_x × 2
    box_height = text_height + padding_y × 2

Valide également :
    - border-radius 16px → coins transparents
    - fond #000000 opaque au centre
    - mode RGBA
    - identité de la formule pour différents textes et paddings
"""

import pytest
from PIL import Image
from tools.graphics import draw_ui_card, find_font_compensated, measure_text
from tools.config import (
    UI_CARD_BG_COLOR, UI_CARD_TEXT_COLOR,
    UI_CARD_PADDING_X, UI_CARD_PADDING_Y,
    UI_CARD_RADIUS, UI_CARD_FONT_SIZE,
)


# ─── Fixture helpers ──────────────────────────────────────────────────────────

def _measure_card_text(text: str, font_size: int = UI_CARD_FONT_SIZE, weight: str = "regular"):
    """Mesure (tw, th) en cohérence avec draw_ui_card (compensation incluse)."""
    font, _ = find_font_compensated(weight, font_size)
    return measure_text(text, font)


# ─── Dimensions dynamiques ────────────────────────────────────────────────────

class TestDrawUiCardDimensions:
    """La formule box = text + 2×padding doit être exacte pour tout texte."""

    @pytest.mark.parametrize("text", ["29$", "5 000$", "100 000$", "+2 000$", "—"])
    def test_width_equals_text_plus_double_padding(self, text):
        tw, _ = _measure_card_text(text)
        card  = draw_ui_card(text)
        expected_w = tw + UI_CARD_PADDING_X * 2
        assert card.size[0] == expected_w, (
            f"text={text!r} : card.width={card.size[0]} ≠ "
            f"tw({tw}) + 2×pad({UI_CARD_PADDING_X}) = {expected_w}"
        )

    @pytest.mark.parametrize("text", ["29$", "5 000$", "100 000$"])
    def test_height_equals_text_plus_double_padding(self, text):
        _, th = _measure_card_text(text)
        card  = draw_ui_card(text)
        expected_h = th + UI_CARD_PADDING_Y * 2
        assert card.size[1] == expected_h, (
            f"text={text!r} : card.height={card.size[1]} ≠ "
            f"th({th}) + 2×pad({UI_CARD_PADDING_Y}) = {expected_h}"
        )

    def test_custom_padding_respected(self):
        text = "99$"
        px, py = 40, 20
        tw, th = _measure_card_text(text)
        card   = draw_ui_card(text, padding_x=px, padding_y=py)
        assert card.size[0] == tw + px * 2
        assert card.size[1] == th + py * 2

    def test_wider_text_produces_wider_card(self):
        short = draw_ui_card("1$")
        long_ = draw_ui_card("100 000$")
        assert long_.size[0] > short.size[0], (
            "Une chaîne plus longue doit produire une carte plus large"
        )

    def test_minimum_dimensions_positive(self):
        card = draw_ui_card("X")
        assert card.size[0] > 0 and card.size[1] > 0


# ─── Border-radius ────────────────────────────────────────────────────────────

class TestDrawUiCardBorderRadius:
    """Avec radius=16px les pixels de coin doivent être transparents."""

    def test_top_left_corner_transparent(self):
        card = draw_ui_card("5 000$", corner_radius=16)
        assert card.getpixel((0, 0))[3] == 0, "Coin haut-gauche doit être transparent"

    def test_top_right_corner_transparent(self):
        card = draw_ui_card("5 000$", corner_radius=16)
        w    = card.size[0]
        assert card.getpixel((w - 1, 0))[3] == 0, "Coin haut-droit doit être transparent"

    def test_bottom_left_corner_transparent(self):
        card = draw_ui_card("5 000$", corner_radius=16)
        h    = card.size[1]
        assert card.getpixel((0, h - 1))[3] == 0, "Coin bas-gauche doit être transparent"

    def test_bottom_right_corner_transparent(self):
        card = draw_ui_card("5 000$", corner_radius=16)
        w, h = card.size
        assert card.getpixel((w - 1, h - 1))[3] == 0, "Coin bas-droit doit être transparent"

    def test_center_pixel_fully_opaque(self):
        card = draw_ui_card("5 000$", corner_radius=16)
        cx, cy = card.size[0] // 2, card.size[1] // 2
        assert card.getpixel((cx, cy))[3] == 255, "Centre doit être opaque"

    def test_zero_radius_no_transparent_corners(self):
        card = draw_ui_card("99$", corner_radius=0)
        assert card.getpixel((0, 0))[3] == 255, "radius=0 → coin doit être opaque"


# ─── Couleurs et mode ─────────────────────────────────────────────────────────

class TestDrawUiCardColors:
    """Fond noir, mode RGBA, transparence préservée hors des coins."""

    def test_mode_is_rgba(self):
        card = draw_ui_card("49$")
        assert card.mode == "RGBA"

    def test_center_background_is_black(self):
        card   = draw_ui_card("49$", bg_color=(0, 0, 0))
        cx, cy = card.size[0] // 2, card.size[1] // 2
        px     = card.getpixel((cx, cy))
        assert px[:3] == (0, 0, 0), f"Centre doit être noir, obtenu {px[:3]}"
        assert px[3]  == 255,        "Centre doit être opaque"

    def test_custom_bg_color_applied(self):
        card   = draw_ui_card("99$", bg_color=(30, 30, 30), corner_radius=0)
        cx, cy = card.size[0] // 2, card.size[1] // 2
        px     = card.getpixel((cx, cy))
        assert px[:3] == (30, 30, 30), f"Fond custom non appliqué : {px[:3]}"

    def test_returns_pil_image(self):
        card = draw_ui_card("1 000$")
        assert isinstance(card, Image.Image)


# ─── Cohérence render_price_scene ────────────────────────────────────────────

class TestRenderPriceScene:
    """render_price_scene utilise draw_ui_card → vérifier le canvas résultant."""

    def test_output_shape(self):
        import numpy as np
        from tools.graphics import render_price_scene
        arr = render_price_scene("basic")
        assert arr.shape == (1920, 1080, 3), f"Shape inattendu : {arr.shape}"

    def test_price_literal_three_values(self):
        import numpy as np
        from tools.graphics import render_price_scene
        arr = render_price_scene("49$,99$,199$")
        assert arr.shape[0] == 1920 and arr.shape[1] == 1080

    def test_price_scene_not_all_white(self):
        import numpy as np
        from tools.graphics import render_price_scene
        arr = render_price_scene("challenge")
        # Au moins un pixel non-blanc (les cartes noires sont présentes)
        assert not (arr == 255).all(), "La scène ne doit pas être entièrement blanche"
