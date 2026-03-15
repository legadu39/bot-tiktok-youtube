# -*- coding: utf-8 -*-
from typing import Callable, List, Tuple
from PIL import Image, ImageDraw

class SmartLayoutManager:
    def __init__(self, canvas_w: int, canvas_h: int, safe_left: int = 80, safe_right: int = 80, safe_top: int = 200, safe_bottom: int = 350):
        self.W = canvas_w
        self.H = canvas_h
        self.safe_x1 = safe_left
        self.safe_y1 = safe_top
        self.safe_x2 = canvas_w - safe_right
        self.safe_y2 = canvas_h - safe_bottom
        self.safe_w  = self.safe_x2 - self.safe_x1
        self.safe_h  = self.safe_y2 - self.safe_y1

    def fit_fontsize(self, text: str, font_fn: Callable, max_size: int, min_size: int = 30) -> int:
        size = max_size
        while size >= min_size:
            try:
                font = font_fn(size)
                dummy = Image.new("RGBA", (1, 1))
                d     = ImageDraw.Draw(dummy)
                bbox  = d.textbbox((0, 0), text, font=font)
                tw    = bbox[2] - bbox[0]
                if tw <= self.safe_w:
                    return size
            except Exception:
                pass
            size -= 4
        return min_size

    def collides(self, rect_a: Tuple[int, int, int, int], rect_b: Tuple[int, int, int, int], margin: int = 10) -> bool:
        ax, ay, aw, ah = rect_a
        bx, by, bw, bh = rect_b
        return not (ax + aw + margin < bx or bx + bw + margin < ax or ay + ah + margin < by or by + bh + margin < ay)

    def resolve_overlaps(self, rects: List[Tuple[int, int, int, int]], gap: int = 20) -> List[Tuple[int, int, int, int]]:
        resolved = list(rects)
        for i in range(1, len(resolved)):
            for j in range(i):
                while self.collides(resolved[j], resolved[i]):
                    x, y, w, h = resolved[i]
                    resolved[i] = (x, y + gap, w, h)
        return resolved

    def vertical_center_layout(self, heights: List[int], gap: int = 20, cy_anchor: int = None) -> List[int]:
        cy = cy_anchor if cy_anchor is not None else self.H // 2
        total_h = sum(heights) + gap * (len(heights) - 1)
        start_y = cy - total_h // 2
        ys = []
        y  = start_y
        for h in heights:
            ys.append(y)
            y += h + gap
        return ys

    def wrap_text(self, text: str, font_fn: Callable, size: int, max_w: int = None) -> List[str]:
        max_w  = max_w or self.safe_w
        words  = text.split()
        lines  = []
        current = []
        try:
            font  = font_fn(size)
            dummy = Image.new("RGBA", (1, 1))
            d     = ImageDraw.Draw(dummy)

            for word in words:
                test = " ".join(current + [word])
                bbox = d.textbbox((0, 0), test, font=font)
                if bbox[2] - bbox[0] > max_w and current:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))
        except Exception:
            lines = [text]
        return lines or [text]