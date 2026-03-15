# -*- coding: utf-8 -*-
import math
import random
import numpy as np
from PIL import Image, ImageDraw
from dataclasses import dataclass
from typing import Tuple, List

@dataclass
class SparkleParticle:
    cx:       int
    cy:       int
    orbit_rx: float = 80.0
    orbit_ry: float = 40.0
    phase:    float = 0.0
    speed:    float = 1.2    # rad/s
    radius:   int   = 6
    color:    Tuple[int,int,int] = (123, 108, 246)   # Purple #7B6CF6
    alpha:    float = 0.75

    def position(self, t: float) -> Tuple[int, int]:
        angle = self.phase + self.speed * t
        x = int(self.cx + self.orbit_rx * math.cos(angle))
        y = int(self.cy + self.orbit_ry * math.sin(angle))
        return (x, y)

def build_sparkles(cx: int, cy: int, n: int = 4, orbit_rx: float = 90.0, orbit_ry: float = 45.0) -> List[SparkleParticle]:
    palette = [
        (123, 108, 246), (200, 180, 255), (80,  180, 255),
        (255, 200, 80),  (140, 220, 160),
    ]
    particles = []
    for i in range(n):
        phase = (2.0 * math.pi / n) * i + random.uniform(-0.3, 0.3)
        speed = random.uniform(0.8, 1.6)
        col   = palette[i % len(palette)]
        r     = random.randint(5, 8)
        alpha = random.uniform(0.55, 0.85)
        particles.append(SparkleParticle(
            cx=cx, cy=cy,
            orbit_rx=orbit_rx + random.uniform(-20, 20),
            orbit_ry=orbit_ry + random.uniform(-10, 10),
            phase=phase, speed=speed,
            radius=r, color=col, alpha=alpha,
        ))
    return particles

def draw_sparkles(frame: np.ndarray, particles: List[SparkleParticle], t: float, inverted: bool = True) -> np.ndarray:
    if not particles or not inverted:
        return frame
    img  = Image.fromarray(frame).convert("RGBA")
    over = Image.new("RGBA", img.size, (0,0,0,0))
    draw = ImageDraw.Draw(over)
    for p in particles:
        x, y = p.position(t)
        r    = p.radius
        a    = int(p.alpha * 255)
        for glow_r, glow_a in [(r+4, a//4), (r+2, a//2)]:
            draw.ellipse([x-glow_r, y-glow_r, x+glow_r, y+glow_r],
                         fill=p.color + (glow_a,))
        draw.ellipse([x-r, y-r, x+r, y+r], fill=p.color + (a,))
    result = Image.alpha_composite(img, over)
    return np.array(result.convert("RGB"))