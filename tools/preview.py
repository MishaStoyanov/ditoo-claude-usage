"""Render docs/preview.png: what the Ditoo screen looks like with sample usage values."""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ditoo_usage import BLACK, TRACK, render  # noqa: E402

CELL, GAP, PAD = 22, 3, 24
SAMPLE = [
    ("M", (217, 119, 87), (35, 22)),
    ("W", (40, 110, 255), (70, 64)),
    ("S", (170, 60, 255), (95, 88)),
]


def main():
    px = render(SAMPLE)
    size = PAD * 2 + 16 * CELL + 15 * GAP
    img = Image.new("RGB", (size, size), (14, 14, 16))
    draw = ImageDraw.Draw(img)
    for i, color in enumerate(px):
        x, y = i % 16, i // 16
        x0 = PAD + x * (CELL + GAP)
        y0 = PAD + y * (CELL + GAP)
        # the LED panel shows near-black differently than a monitor, so lift the dark tones a bit
        fill = {BLACK: (24, 24, 27), TRACK: (52, 52, 58)}.get(color, color)
        draw.rounded_rectangle([x0, y0, x0 + CELL - 1, y0 + CELL - 1], radius=4, fill=fill)
    out = os.path.join(ROOT, "docs", "preview.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print(out)


if __name__ == "__main__":
    main()
