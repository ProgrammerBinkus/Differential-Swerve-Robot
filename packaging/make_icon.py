"""Draw the app icon (station/assets/icon.ico): the chassis from above, in the wiring sheet's colors.

    python packaging/make_icon.py

Needs Pillow (requirements-build.txt). The generated icon is committed, so
this only needs running again to change the design.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "station" / "assets" / "icon.ico"
SIZE = 1024  # drawn large, then downsampled for each icon size
PAPER, SHEET, RULE, INK, HIGHLIGHT, OK = "#11171B", "#182026", "#33414B", "#E4EAEE", "#F5C518", "#69DB7C"


def rotated_box(cx: float, cy: float, half_length: float, half_width: float, angle_deg: float):
    a = math.radians(angle_deg)
    ux, uy, px, py = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    return [(cx + ux * sl * half_length + px * sw * half_width, cy + uy * sl * half_length + py * sw * half_width)
            for sl, sw in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    s = SIZE / 1000
    d.rounded_rectangle((20 * s, 20 * s, 980 * s, 980 * s), radius=180 * s, fill=PAPER)

    # Chassis: four pods joined by a body that is slimmer between them.
    pods = ((285, 285), (715, 285), (285, 715), (715, 715))
    d.rounded_rectangle((210 * s, 210 * s, 790 * s, 790 * s), radius=60 * s, fill=SHEET, outline=RULE, width=int(14 * s))
    for cx, cy in pods:
        r = 175
        d.ellipse(((cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s), fill=SHEET, outline=INK, width=int(18 * s))
    # Wheels, all steered to the same angle, as swerve does.
    for cx, cy in pods:
        d.polygon([(x * s, y * s) for x, y in rotated_box(cx, cy, 105, 42, -45)], fill=INK)
    # The Orange Pi at the rear, in the selection yellow.
    d.rounded_rectangle((440 * s, 560 * s, 560 * s, 700 * s), radius=14 * s, fill=HIGHLIGHT)
    # Direction of travel.
    d.polygon([(500 * s, 300 * s), (450 * s, 390 * s), (550 * s, 390 * s)], fill=OK)
    return image


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
