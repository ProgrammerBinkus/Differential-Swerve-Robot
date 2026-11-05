"""Top-down view of the robot: parts, wheel headings and wheel motion vectors."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, Callable, Optional

from common.config import MODULE_NAMES
from station import theme
from station.parts import MODULE_CENTERS, MODULE_POD_RADIUS, PARTS

# Visible area in part coordinates (x0, y0, x1, y1), with room for the FRONT marker.
_VIEW = (-15.0, -75.0, 1015.0, 1015.0)
_WHEEL_HALF_LENGTH = 92
_WHEEL_HALF_WIDTH = 32
_ARROW_MIN = 45
_ARROW_SPAN = 150


def _heading_vector(angle_deg: float) -> tuple[float, float]:
    """Screen direction of a robot-frame heading (0 = forward/up, counter-clockwise positive)."""
    rad = math.radians(angle_deg)
    return -math.sin(rad), -math.cos(rad)


def _rounded_square(x0: float, y0: float, x1: float, y1: float, r: float, steps: int = 10) -> list[float]:
    points: list[float] = []
    corners = ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180))
    for cx, cy, start in corners:
        for i in range(steps + 1):
            a = math.radians(start + 90 * i / steps)
            points += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return points


class RobotView(tk.Canvas):
    """Draws the chassis from above, front at the top and the Orange Pi at the rear.

    Wheel rectangles turn to the angle the robot reports, a dashed line shows
    each module's target angle, and an arrow shows which way the robot thinks
    the wheel is rolling (length = drive command). Clicking a part or a module
    calls ``on_select`` with its ID.
    """

    def __init__(self, parent: tk.Misc, on_select: Callable[[Optional[str]], None]) -> None:
        super().__init__(parent, bg=theme.BG, highlightthickness=0, width=620, height=620)
        self._on_select = on_select
        self._scale = 1.0
        self._origin = (0.0, 0.0)
        self._selected: Optional[str] = None
        self._outlines: dict[str, tuple[int, str]] = {}  # part id -> (canvas item, normal color)
        self._modules: dict[str, Any] = {}
        self._wheels: dict[str, dict[str, int]] = {}
        self.bind("<Configure>", lambda _e: self._draw())
        self.tag_bind("part", "<Button-1>", self._on_click)
        self.bind("<Button-1>", self._on_background_click, add="+")
        self.tag_bind("part", "<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.tag_bind("part", "<Leave>", lambda _e: self.configure(cursor=""))

    # ---------------------------------------------------------------- public

    def update_modules(self, modules: Optional[dict[str, Any]]) -> None:
        """Redraw wheels from a telemetry ``modules`` dict (``None`` when the robot is not connected)."""
        self._modules = modules or {}
        for name in MODULE_NAMES:
            self._draw_wheel(name)

    def select(self, part_id: Optional[str]) -> None:
        if self._selected in self._outlines:
            item, color = self._outlines[self._selected]
            self.itemconfigure(item, outline=color, width=1.5)
        self._selected = part_id
        if part_id in self._outlines:
            self.itemconfigure(self._outlines[part_id][0], outline=theme.HIGHLIGHT, width=3)

    # --------------------------------------------------------------- drawing

    def _to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self._origin[0] + x * self._scale, self._origin[1] + y * self._scale

    def _points(self, *coords: float) -> list[float]:
        out = []
        for i in range(0, len(coords), 2):
            out += self._to_screen(coords[i], coords[i + 1])
        return out

    def _draw(self) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        view_w, view_h = _VIEW[2] - _VIEW[0], _VIEW[3] - _VIEW[1]
        self._scale = min(width / view_w, height / view_h)
        self._origin = ((width - view_w * self._scale) / 2 - _VIEW[0] * self._scale,
                        (height - view_h * self._scale) / 2 - _VIEW[1] * self._scale)
        self.delete("all")
        self._outlines.clear()
        self._wheels.clear()
        font_size = max(9, int(round(16 * self._scale)))
        label_font = ("Segoe UI Semibold", font_size)
        small_font = ("Segoe UI", max(8, font_size - 2))

        self.create_polygon(self._points(*_rounded_square(30, 30, 970, 970, 210)), smooth=False,
                            fill=theme.SURFACE, outline=theme.BORDER, width=2)

        # Front marker.
        self.create_polygon(self._points(500, -66, 486, -40, 514, -40), fill=theme.TEXT, outline="")
        self.create_text(*self._to_screen(500, -22), text="FRONT", fill=theme.TEXT, font=label_font)

        for name, (cx, cy) in MODULE_CENTERS.items():
            r = MODULE_POD_RADIUS
            pod = self.create_oval(*self._points(cx - r, cy - r, cx + r, cy + r), fill=theme.SURFACE_2,
                                   outline=theme.BORDER, width=1.5, tags=("part", f"id={name}"))
            self._outlines[name] = (pod, theme.BORDER)
            g = r - 30
            self.create_oval(*self._points(cx - g, cy - g, cx + g, cy + g), outline=theme.BORDER, dash=(3, 4))
            label_y = cy - r - 18 if cy < 500 else cy + r + 18
            self.create_text(*self._to_screen(cx, label_y), text=f"{name} module", fill=theme.MUTED,
                             font=small_font)
            module_tags = ("part", f"id={name}")
            self._wheels[name] = {
                "target": self.create_line(0, 0, 0, 0, fill=theme.MUTED, dash=(4, 4), width=2, tags=module_tags),
                "wheel": self.create_polygon(0, 0, 0, 0, 0, 0, fill=theme.BORDER, outline=theme.TEXT, width=1.5,
                                             tags=module_tags),
                "arrow": self.create_line(0, 0, 0, 0, fill=theme.CONTROL, width=max(2, 5 * self._scale),
                                          arrow="last", arrowshape=(12, 14, 5), state="hidden",
                                          tags=module_tags),
                "text": self.create_text(*self._to_screen(cx, cy + (r - 20 if cy < 500 else -r + 20)),
                                         text="", fill=theme.TEXT, font=small_font),
            }

        for part in PARTS:
            x0, y0 = part.x - part.w / 2, part.y - part.h / 2
            item = self.create_rectangle(*self._points(x0, y0, x0 + part.w, y0 + part.h), fill=theme.SURFACE_2,
                                         outline=part.color, width=1.5, tags=("part", f"id={part.id}"))
            self._outlines[part.id] = (item, part.color)
            text_font = label_font if part.kind in ("compute", "power") and part.w > 60 else small_font
            self.create_text(*self._to_screen(part.x, part.y), text=part.label, fill=theme.TEXT,
                             font=text_font, width=max(20, part.w * self._scale - 4),
                             justify="center", tags=("part", f"id={part.id}"))

        self.create_text(*self._to_screen(505, 1000), text="REAR", fill=theme.MUTED, font=small_font)
        self.update_modules(self._modules)
        self.select(self._selected)

    def _draw_wheel(self, name: str) -> None:
        items = self._wheels.get(name)
        if not items:
            return
        cx, cy = MODULE_CENTERS[name]
        live = self._modules.get(name)
        angle = live["angle"] if live and live["angle"] is not None else 0.0
        ux, uy = _heading_vector(angle)
        px, py = -uy, ux
        L, W = _WHEEL_HALF_LENGTH, _WHEEL_HALF_WIDTH
        corners = (cx + ux * L + px * W, cy + uy * L + py * W, cx + ux * L - px * W, cy + uy * L - py * W,
                   cx - ux * L - px * W, cy - uy * L - py * W, cx - ux * L + px * W, cy - uy * L + py * W)
        self.coords(items["wheel"], *self._points(*corners))

        if not live:
            self.itemconfigure(items["wheel"], fill=theme.BORDER)
            self.itemconfigure(items["arrow"], state="hidden")
            self.itemconfigure(items["target"], state="hidden")
            self.itemconfigure(items["text"], text="no data")
            return

        self.itemconfigure(items["wheel"], fill=theme.ERROR if live["fault"] else "#3a4654")
        if live["target"] is not None:
            tx, ty = _heading_vector(live["target"])
            self.coords(items["target"], *self._points(cx - tx * 135, cy - ty * 135, cx + tx * 135, cy + ty * 135))
            self.itemconfigure(items["target"], state="normal")
        drive = live["drive"]
        if abs(drive) > 0.01:
            direction = 1.0 if drive > 0 else -1.0
            length = _ARROW_MIN + _ARROW_SPAN * min(1.0, abs(drive))
            self.coords(items["arrow"], *self._points(cx, cy, cx + ux * direction * length,
                                                      cy + uy * direction * length))
            self.itemconfigure(items["arrow"], state="normal")
        else:
            self.itemconfigure(items["arrow"], state="hidden")
        self.itemconfigure(items["text"], text=f"{angle:+.0f}°  {drive * 100:+.0f}%")

    # ---------------------------------------------------------------- clicks

    def _on_click(self, _event: tk.Event) -> None:
        for tag in self.gettags("current"):
            if tag.startswith("id="):
                self._on_select(tag[3:])
                return

    def _on_background_click(self, _event: tk.Event) -> None:
        if "part" not in self.gettags("current"):
            self._on_select(None)
