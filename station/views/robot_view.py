"""Top-down view of the robot, drawn like wiring sheet E-01.

Parts are ink-outlined boxes on the chassis outline, harnesses are colored by
layer, and the selected part turns yellow while everything not connected to
it fades. On top of the sheet, each wheel turns to the angle the robot
reports, a dashed line shows its target angle, and an arrow shows which way
the robot is rolling it and how hard.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, Callable, Optional

from common.config import MODULE_NAMES
from station import theme
from station.parts import MODULE_CENTERS, MODULE_POD_RADIUS, PARTS, WIRE_LAYERS, WIRES

# Visible area in part coordinates (x0, y0, x1, y1), with room for the FRONT marker.
_VIEW = (-15.0, -80.0, 1015.0, 1015.0)
_WHEEL_HALF_LENGTH = 92
_WHEEL_HALF_WIDTH = 32
_ARROW_MIN = 45
_ARROW_SPAN = 150
_ENCODER_GEARS = ((330, 325), (680, 325), (330, 675), (680, 675))
_DIAL_CENTER, _DIAL_RADIUS = (958.0, -28.0), 40.0   # field heading dial, top right, outside the chassis

LAYER_COLORS = {
    "battery": theme.WIRE_BATTERY, "5v": theme.WIRE_5V, "control": theme.WIRE_CONTROL,
    "motor": theme.WIRE_MOTOR, "i2c": theme.WIRE_I2C,
}
_LAYER_WIDTHS = {"battery": 5.0, "motor": 3.0}  # others 3.6, as on the sheet


def heading_vector(angle_deg: float) -> tuple[float, float]:
    """Screen direction of a robot-frame heading (0 = forward/up, counter-clockwise positive)."""
    rad = math.radians(angle_deg)
    return -math.sin(rad), -math.cos(rad)


def chassis_outline(rim: float = 170, edge: float = 65, steps: int = 24) -> list[float]:
    """The CAD outline: a rim around each corner pod, joined by straight sides set in between the pods.

    Each pod's arc runs between the two points where its rim circle meets the
    neighboring sides; the polygon is drawn smoothed, which rounds the joins.
    """
    inset = MODULE_CENTERS["FL"][0] - edge             # pod center to side line
    reach = math.sqrt(rim * rim - inset * inset)       # along the side, to the join
    join = math.degrees(math.atan2(reach, inset))
    span = 90 + 2 * join
    points: list[float] = []
    # Clockwise on screen (+y down), starting at the FL pod's join with the left side.
    for index, name in enumerate(("FL", "FR", "BR", "BL")):
        cx, cy = MODULE_CENTERS[name]
        start = 180 - join + 90 * index
        for i in range(steps + 1):
            a = math.radians(start + span * i / steps)
            points += [cx + rim * math.cos(a), cy + rim * math.sin(a)]
    return points


def wheel_outline(cx: float, cy: float, ux: float, uy: float, half_length: float, half_width: float,
                   radius: float = 18, steps: int = 5) -> list[float]:
    """A rounded-corner wheel centered on (cx, cy), its length along the unit vector (ux, uy)."""
    px, py = -uy, ux
    points: list[float] = []
    for corner, (sa, sb) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        a0, b0 = sa * (half_length - radius), sb * (half_width - radius)
        for i in range(steps + 1):
            t = math.radians(90 * corner + 90 * i / steps)
            a, b = a0 + radius * math.cos(t), b0 + radius * math.sin(t)
            points += [cx + ux * a + px * b, cy + uy * a + py * b]
    return points


class RobotView(tk.Canvas):
    """The plan-view drawing. Clicking a part or module calls ``on_select`` with its ID."""

    def __init__(self, parent: tk.Misc, on_select: Callable[[Optional[str]], None]) -> None:
        super().__init__(parent, bg=theme.SHEET, highlightthickness=0, width=620, height=620)
        self._on_select = on_select
        self._scale = 1.0
        self._origin = (0.0, 0.0)
        self._selected: Optional[str] = None
        self._hidden_layers: set[str] = set()
        self._modules: dict[str, Any] = {}
        self._parts: dict[str, tuple[int, int]] = {}            # part id -> (box, label)
        self._pods: dict[str, int] = {}
        self._wires: dict[str, list[tuple[int, float]]] = {}     # wire id -> [(core item, width)]
        self._wheels: dict[str, dict[str, int]] = {}
        self._dial: dict[str, int] = {}
        self._heading: Optional[float] = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.tag_bind("pickable", "<Button-1>", self._on_click)
        self.bind("<Button-1>", self._on_background_click, add="+")
        self.tag_bind("pickable", "<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.tag_bind("pickable", "<Leave>", lambda _e: self.configure(cursor=""))

    # ---------------------------------------------------------------- public

    def update_modules(self, modules: Optional[dict[str, Any]]) -> None:
        """Redraw wheels from a telemetry ``modules`` dict (``None`` when the robot is not connected)."""
        self._modules = modules or {}
        for name in MODULE_NAMES:
            self._draw_wheel(name)

    def update_heading(self, heading_deg: Optional[float]) -> None:
        """Turn the field dial: its arrow points "away from the driver station" as seen from the robot."""
        self._heading = heading_deg
        dial = self._dial
        if not dial:
            return
        cx, cy = _DIAL_CENTER
        if heading_deg is None:
            for key in ("arrow", "you"):
                self.itemconfigure(dial[key], state="hidden")
            self.itemconfigure(dial["text"], text="NO HEADING")
            return
        # Field forward in the robot frame is the robot's heading turned back by itself.
        ux, uy = heading_vector(-heading_deg)
        r = _DIAL_RADIUS - 8
        self.coords(dial["arrow"], *self._points(cx - ux * r, cy - uy * r, cx + ux * r, cy + uy * r))
        you_x, you_y = self._to_screen(cx - ux * r, cy - uy * r)
        dot = 4.5 * self._scale * 1.6
        self.coords(dial["you"], you_x - dot, you_y - dot, you_x + dot, you_y + dot)
        for key in ("arrow", "you"):
            self.itemconfigure(dial[key], state="normal")
        self.itemconfigure(dial["text"], text=f"FIELD {round(heading_deg):+d}°")

    def select(self, part_id: Optional[str]) -> None:
        self._selected = part_id
        self._apply_selection()

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        (self._hidden_layers.discard if visible else self._hidden_layers.add)(layer)
        self.itemconfigure(f"layer-{layer}", state="normal" if visible else "hidden")

    # --------------------------------------------------------------- drawing

    def _to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self._origin[0] + x * self._scale, self._origin[1] + y * self._scale

    def _points(self, *coords: float) -> list[float]:
        out = []
        for i in range(0, len(coords), 2):
            out += self._to_screen(coords[i], coords[i + 1])
        return out

    def _flat(self, points) -> list[float]:
        return self._points(*(value for point in points for value in point))

    def _draw(self) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        view_w, view_h = _VIEW[2] - _VIEW[0], _VIEW[3] - _VIEW[1]
        self._scale = min(width / view_w, height / view_h)
        self._origin = ((width - view_w * self._scale) / 2 - _VIEW[0] * self._scale,
                        (height - view_h * self._scale) / 2 - _VIEW[1] * self._scale)
        self.delete("all")
        self._parts.clear()
        self._pods.clear()
        self._wires.clear()
        self._wheels.clear()
        self._dial.clear()
        s = self._scale
        size = max(9, round(17 * s))
        title_font = (theme.DISPLAY, size)
        small_font = (theme.DISPLAY, max(8, size - 3))
        mono_font = (theme.MONO, max(8, round(13 * s)))

        # Chassis outline, module pods, gears.
        self.create_polygon(self._points(*chassis_outline()), smooth=True, fill=theme.PAPER,
                            outline=theme.RULE, width=1.5)
        for name, (cx, cy) in MODULE_CENTERS.items():
            r = MODULE_POD_RADIUS
            self._pods[name] = self.create_oval(*self._points(cx - r, cy - r, cx + r, cy + r), fill=theme.PAPER,
                                                outline=theme.RULE, width=1.5, tags=("pickable", f"id={name}"))
            for radius, dash in ((r - 30, (3, 4)), (48, ())):
                self.create_oval(*self._points(cx - radius, cy - radius, cx + radius, cy + radius),
                                 outline=theme.RULE if dash else theme.FAINT, dash=dash, width=1.2)
            label_y = cy - r - 36 if cy < 500 else cy + r + 36  # just outside the chassis rim
            self.create_text(*self._to_screen(cx, label_y), text=f"{name} MODULE", fill=theme.MUTED,
                             font=small_font)
        for cx, cy in _ENCODER_GEARS:
            self.create_oval(*self._points(cx - 52, cy - 52, cx + 52, cy + 52), outline=theme.RULE, dash=(3, 4))

        # Front marker.
        self.create_polygon(self._points(500, -72, 487, -48, 513, -48), fill=theme.INK, outline="")
        self.create_text(*self._to_screen(500, -26), text="F R O N T", fill=theme.INK, font=title_font)
        self.create_text(*self._to_screen(505, 1000), text="R E A R", fill=theme.MUTED, font=small_font)

        # Harnesses: a halo the color of the chassis, then the colored core.
        for layer, _label in WIRE_LAYERS:
            color = LAYER_COLORS[layer]
            for wire in (w for w in WIRES if w.layer == layer):
                core_width = _LAYER_WIDTHS.get(layer, 3.6) * s
                runs = [wire.points] + ([wire.branch] if wire.branch else [])
                tags = (f"layer-{layer}",)
                for run in runs:
                    self.create_line(*self._flat(run), fill=theme.PAPER, width=core_width + 5 * s,
                                     capstyle="round", joinstyle="round", tags=tags)
                cores = []
                for run in runs:
                    cores.append((self.create_line(*self._flat(run), fill=color, width=core_width,
                                                   capstyle="round", joinstyle="round", tags=tags), core_width))
                if wire.branch:
                    x, y = self._to_screen(*wire.branch[0])
                    r = 5 * s
                    cores.append((self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="", tags=tags), 0))
                self._wires[wire.id] = cores

        # Parts.
        for part in PARTS:
            x0, y0 = part.x - part.w / 2, part.y - part.h / 2
            box = self.create_rectangle(*self._points(x0, y0, x0 + part.w, y0 + part.h), fill=theme.SHEET,
                                        outline=theme.INK, width=1.6, tags=("pickable", f"id={part.id}"))
            big = part.kind in ("compute", "power") and part.w > 60
            upright = part.h > part.w * 1.4 and len(part.label) > 3  # tall, narrow box: run the label up it
            label = self.create_text(*self._to_screen(part.x, part.y), text=part.label, fill=theme.INK,
                                     font=title_font if big else small_font, justify="center",
                                     angle=90 if upright else 0,
                                     width=0 if upright else max(20, part.w * s - 4),
                                     tags=("pickable", f"id={part.id}"))
            self._parts[part.id] = (box, label)

        # Wheels, drawn last so they sit on top.
        for name, (cx, cy) in MODULE_CENTERS.items():
            r = MODULE_POD_RADIUS
            tags = ("pickable", f"id={name}")
            self._wheels[name] = {
                "target": self.create_line(0, 0, 0, 0, fill=theme.MUTED, dash=(5, 4), width=1.5, tags=tags),
                "wheel": self.create_polygon(0, 0, 0, 0, 0, 0, fill=theme.FAINT, outline=theme.INK, width=1.6,
                                             tags=tags),
                "arrow": self.create_line(0, 0, 0, 0, fill=theme.OK, width=max(2, 5 * s), arrow="last",
                                          arrowshape=(12, 14, 5), capstyle="round", state="hidden", tags=tags),
                "text": self.create_text(*self._to_screen(cx, cy + (r - 22 if cy < 500 else -r + 22)),
                                         text="", fill=theme.MUTED, font=mono_font),
            }

        # Field heading dial: arrow = away from the driver station, dot = the driver station's side.
        cx, cy = _DIAL_CENTER
        r = _DIAL_RADIUS
        self.create_oval(*self._points(cx - r, cy - r, cx + r, cy + r), fill=theme.PAPER, outline=theme.RULE, width=1.5)
        self._dial = {
            "arrow": self.create_line(0, 0, 0, 0, fill=theme.HIGHLIGHT, width=max(2, 4 * s), arrow="last",
                                      arrowshape=(9, 11, 4), capstyle="round"),
            "you": self.create_oval(0, 0, 0, 0, fill=theme.INK, outline=""),
            "text": self.create_text(*self._to_screen(cx, cy + r + 16), text="", fill=theme.MUTED, font=small_font),
        }

        for layer in self._hidden_layers:
            self.itemconfigure(f"layer-{layer}", state="hidden")
        self.update_modules(self._modules)
        self.update_heading(self._heading)
        self._apply_selection()

    def _apply_selection(self) -> None:
        selected = self._selected
        related_wires = {w.id for w in WIRES if selected in w.ends}
        related_parts = {end for w in WIRES if w.id in related_wires for end in w.ends}
        tracing = selected in self._parts and bool(related_wires)

        for part_id, (box, label) in self._parts.items():
            if part_id == selected:
                self.itemconfigure(box, fill=theme.HIGHLIGHT, outline=theme.INK, width=2.4)
                self.itemconfigure(label, fill=theme.HIGHLIGHT_INK)
            elif tracing and part_id not in related_parts:
                self.itemconfigure(box, fill=theme.SHEET, outline=theme.RULE, width=1.6)
                self.itemconfigure(label, fill=theme.RULE)
            else:
                self.itemconfigure(box, fill=theme.SHEET, outline=theme.INK, width=1.6)
                self.itemconfigure(label, fill=theme.INK)

        for wire in WIRES:
            color = LAYER_COLORS[wire.layer]
            for item, width in self._wires.get(wire.id, []):
                if width == 0:  # junction dot
                    self.itemconfigure(item, fill=theme.FAINT if tracing and wire.id not in related_wires else color)
                elif tracing and wire.id in related_wires:
                    self.itemconfigure(item, fill=color, width=width * 1.6)
                elif tracing:
                    self.itemconfigure(item, fill=theme.FAINT, width=width)
                else:
                    self.itemconfigure(item, fill=color, width=width)

        for name, pod in self._pods.items():
            self.itemconfigure(pod, outline=theme.HIGHLIGHT if name == selected else theme.RULE,
                               width=2.4 if name == selected else 1.5)

    def _draw_wheel(self, name: str) -> None:
        items = self._wheels.get(name)
        if not items:
            return
        cx, cy = MODULE_CENTERS[name]
        live = self._modules.get(name)
        angle = live["angle"] if live and live["angle"] is not None else 0.0
        ux, uy = heading_vector(angle)
        outline = wheel_outline(cx, cy, ux, uy, _WHEEL_HALF_LENGTH, _WHEEL_HALF_WIDTH)
        self.coords(items["wheel"], *self._points(*outline))

        if not live:
            self.itemconfigure(items["wheel"], outline=theme.RULE)
            self.itemconfigure(items["arrow"], state="hidden")
            self.itemconfigure(items["target"], state="hidden")
            self.itemconfigure(items["text"], text="NO DATA")
            return

        self.itemconfigure(items["wheel"], outline=theme.ERROR if live["fault"] else theme.INK)
        if live["target"] is not None:
            tx, ty = heading_vector(live["target"])
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
        if "pickable" not in self.gettags("current"):
            self._on_select(None)
