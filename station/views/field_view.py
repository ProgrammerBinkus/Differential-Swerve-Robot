"""Field view: the robot seen from above as it moves over the field.

Only the chassis outline, the wheels (at their angle on the field) and their
motion vectors are drawn; the electronics are left out. The field frame is
the one field-relative drive uses: up on the screen is "away from the driver
station", set with *Set field forward*.

The view follows the robot over a 0.5 m grid and leaves a trail behind it.
Each point of the trail disappears ``TRAIL_SECONDS`` after the robot passed
it, so the trail follows the robot and fades out when it stops; its older
half is drawn dimmer.
Position comes from the simulator; the real robot has no drive encoders, so
it cannot measure where it is. It is then drawn at the center with its true
heading, and a note says so.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from collections import deque
from typing import Any, Optional

from common.config import MODULE_NAMES
from station import theme
from station.parts import MODULE_CENTERS
from station.views.robot_view import chassis_outline

GRID_M = 0.5
TRAIL_SECONDS = 10.0             # a point is dropped this long after the robot passed it
TRAIL_POINTS = 2000              # hard cap, far above 10 s of points at the UI refresh rate
TRAIL_MIN_STEP_M = 0.01
SPAN_LIMITS_M = (2.0, 20.0)      # zoom range: field width visible across the view
DRIVER_STATION_X_M = -0.75       # drawn just behind the point where field forward was set

# Part coordinates (the 1000-unit box of the robot view) to robot-frame meters.
_PART_CENTER = 500.0
_PART_MODULE_SPAN = MODULE_CENTERS["FR"][0] - MODULE_CENTERS["FL"][0]
_WHEEL_HALF_LENGTH, _WHEEL_HALF_WIDTH, _WHEEL_CORNER = 92.0, 32.0, 18.0   # same wheel as the robot view
_ARROW_MIN, _ARROW_SPAN = 45.0, 150.0


def robot_to_field(x: float, y: float, pose: tuple[float, float], heading_deg: float) -> tuple[float, float]:
    """A robot-frame point (+x forward, +y left, meters) on the field."""
    h = math.radians(heading_deg)
    return pose[0] + x * math.cos(h) - y * math.sin(h), pose[1] + x * math.sin(h) + y * math.cos(h)


class FieldView(tk.Canvas):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.SHEET, highlightthickness=0, width=620, height=620)
        self._span_m = 2.5
        self._trail: deque[tuple[float, float, float]] = deque(maxlen=TRAIL_POINTS)  # (x, y, time)
        self._clock = time.monotonic
        self._epoch: Optional[int] = None
        self._modules: dict[str, Any] = {}
        self._heading: Optional[float] = None
        self._pose: Optional[tuple[float, float]] = None
        self._module_offset_m = 0.11
        self._imu_status: Optional[str] = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<MouseWheel>", self._on_wheel)

    # ---------------------------------------------------------------- public

    def update_state(self, modules: Optional[dict[str, Any]], heading_deg: Optional[float],
                     pose: Optional[dict[str, Any]], module_offset_m: Optional[float],
                     imu_status: Optional[str] = None) -> None:
        """New telemetry. ``pose`` is ``{"x", "y", "epoch"}`` from the simulator, or ``None``."""
        self._modules = modules or {}
        self._imu_status = imu_status
        self._heading = heading_deg
        if module_offset_m:
            self._module_offset_m = module_offset_m
        now = self._clock()
        if pose is not None:
            if pose.get("epoch") != self._epoch:      # field forward was set again: a new field frame
                self._epoch = pose.get("epoch")
                self._trail.clear()
            point = (pose["x"], pose["y"])
            if not self._trail or math.dist(point, self._trail[-1][:2]) >= TRAIL_MIN_STEP_M:
                self._trail.append((*point, now))
            self._pose = point
        else:
            self._pose = None
            self._trail.clear()
        self._expire_trail(now)
        self._redraw()

    def _expire_trail(self, now: float) -> None:
        while self._trail and now - self._trail[0][2] > TRAIL_SECONDS:
            self._trail.popleft()

    # --------------------------------------------------------------- drawing

    def _units_per_meter(self) -> float:
        return _PART_MODULE_SPAN / (2.0 * self._module_offset_m)

    def _part_to_robot(self, u: float, v: float) -> tuple[float, float]:
        per_m = self._units_per_meter()
        return (_PART_CENTER - v) / per_m, (_PART_CENTER - u) / per_m

    def _redraw(self) -> None:
        self.delete("all")
        width, height = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        scale = min(width, height) / self._span_m          # pixels per meter
        center = self._pose or (0.0, 0.0)                  # the view follows the robot

        def screen(fx: float, fy: float) -> tuple[float, float]:
            # Field +x is up the screen, field +y is to the left.
            return width / 2 - (fy - center[1]) * scale, height / 2 - (fx - center[0]) * scale

        self._draw_grid(width, height, scale, center, screen)
        self._draw_landmarks(screen, scale)
        self._draw_trail(screen)
        if self._heading is None:
            reason = {"absent": "NO IMU FOUND", "fault": "IMU NOT ANSWERING",
                      "calibrating": "GYRO CALIBRATING: KEEP THE ROBOT STILL"}.get(self._imu_status or "", "NO DATA")
            self.create_text(width / 2, height / 2, text=reason, fill=theme.MUTED, font=theme.display_font(16))
        else:
            self._draw_robot(screen, scale)
        self._draw_overlay(width, height)

    def _draw_trail(self, screen) -> None:
        """The path of the last ``TRAIL_SECONDS``: the newer half brighter than the older half."""
        if len(self._trail) < 2:
            return
        now = self._clock()
        split = next((i for i, (_x, _y, t) in enumerate(self._trail) if now - t <= TRAIL_SECONDS / 2),
                     len(self._trail))
        points = list(self._trail)
        for segment, color in ((points[:split + 1], theme.RULE), (points[split:], theme.MUTED)):
            if len(segment) > 1:
                self.create_line(*[c for x, y, _t in segment for c in screen(x, y)], fill=color, width=2,
                                 smooth=True, capstyle="round", joinstyle="round")

    def _draw_grid(self, width, height, scale, center, screen) -> None:
        half_x, half_y = height / scale / 2 + GRID_M, width / scale / 2 + GRID_M
        first_x = math.floor((center[0] - half_x) / GRID_M)
        for i in range(first_x, first_x + int(2 * half_x / GRID_M) + 2):
            fx = i * GRID_M
            major = i % 2 == 0                               # every meter
            self.create_line(0, screen(fx, 0)[1], width, screen(fx, 0)[1],
                             fill=theme.RULE if major else theme.FAINT)
        first_y = math.floor((center[1] - half_y) / GRID_M)
        for i in range(first_y, first_y + int(2 * half_y / GRID_M) + 2):
            fy = i * GRID_M
            major = i % 2 == 0
            self.create_line(screen(0, fy)[0], 0, screen(0, fy)[0], height,
                             fill=theme.RULE if major else theme.FAINT)

    def _draw_landmarks(self, screen, scale) -> None:
        small = theme.display_font(10)
        x, y = screen(0.0, 0.0)
        r = 6
        self.create_line(x - r, y, x + r, y, fill=theme.MUTED, width=2)
        self.create_line(x, y - r, x, y + r, fill=theme.MUTED, width=2)
        self.create_text(x + 8, y + 8, text="START", anchor="nw", fill=theme.MUTED, font=small)
        left, ds_y = screen(DRIVER_STATION_X_M, 1.0)
        right, _ = screen(DRIVER_STATION_X_M, -1.0)
        self.create_line(left, ds_y, right, ds_y, fill=theme.INK, width=max(3, 0.05 * scale), capstyle="round")
        self.create_text((left + right) / 2, ds_y + 12, text="DRIVER STATION", fill=theme.INK, font=small)

    def _draw_robot(self, screen, scale) -> None:
        pose = self._pose or (0.0, 0.0)
        heading = self._heading

        def field_point(u: float, v: float) -> tuple[float, float]:
            return screen(*robot_to_field(*self._part_to_robot(u, v), pose, heading))

        outline = chassis_outline()
        points = [c for i in range(0, len(outline), 2) for c in field_point(outline[i], outline[i + 1])]
        self.create_polygon(points, smooth=True, fill=theme.PAPER, outline=theme.RULE, width=1.5)
        # Front marker, so the heading reads at a glance.
        self.create_polygon(*field_point(500, 40), *field_point(470, 95), *field_point(530, 95),
                            fill=theme.INK, outline="")

        per_m = self._units_per_meter()
        for name in MODULE_NAMES:
            module = self._modules.get(name)
            if not module or module.get("angle") is None:
                continue
            cx, cy = robot_to_field(*self._part_to_robot(*MODULE_CENTERS[name]), pose, heading)
            angle = math.radians(heading + module["angle"])          # the wheel's direction on the field
            ux, uy = math.cos(angle), math.sin(angle)
            wheel = self._rounded_wheel(cx, cy, ux, uy, _WHEEL_HALF_LENGTH / per_m, _WHEEL_HALF_WIDTH / per_m,
                                        _WHEEL_CORNER / per_m)
            self.create_polygon([c for point in wheel for c in screen(*point)],
                                fill=theme.FAINT, outline=theme.ERROR if module.get("fault") else theme.INK,
                                width=1.6)
            drive = module.get("drive", 0.0)
            if abs(drive) > 0.01:
                length = (_ARROW_MIN + _ARROW_SPAN * min(1.0, abs(drive))) / per_m * math.copysign(1.0, drive)
                self.create_line(*screen(cx, cy), *screen(cx + ux * length, cy + uy * length), fill=theme.OK,
                                 width=max(2, 0.012 * scale), arrow="last", arrowshape=(10, 12, 4),
                                 capstyle="round")

    @staticmethod
    def _rounded_wheel(cx: float, cy: float, ux: float, uy: float, half_length: float, half_width: float,
                       radius: float, steps: int = 4) -> list[tuple[float, float]]:
        px, py = -uy, ux
        points = []
        for corner, (sa, sb) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
            a0, b0 = sa * (half_length - radius), sb * (half_width - radius)
            for i in range(steps + 1):
                t = math.radians(90 * corner + 90 * i / steps)
                a, b = a0 + radius * math.cos(t), b0 + radius * math.sin(t)
                points.append((cx + ux * a + px * b, cy + uy * a + py * b))
        return points

    def _draw_overlay(self, width, height) -> None:
        label, mono = theme.FONT_LABEL, (theme.MONO, 10)
        self.create_text(width / 2, 14, text="▲  AWAY FROM THE DRIVER STATION", fill=theme.MUTED, font=label)
        lines = []
        if self._pose is not None:
            lines.append(f"x {self._pose[0]:+6.2f} m    y {self._pose[1]:+6.2f} m")
        if self._heading is not None:
            lines.append(f"heading {round(self._heading):+d}°")
        self.create_text(12, height - 12, text="\n".join(lines), anchor="sw", fill=theme.INK, font=mono)
        if self._pose is None and self._heading is not None:
            self.create_text(width - 12, height - 12, anchor="se", justify="right", fill=theme.WARN,
                             font=theme.FONT_SMALL,
                             text="No position: the robot has no drive encoders.\nShowing heading only.")
        self.create_text(width - 12, 14, anchor="ne", fill=theme.MUTED, font=theme.FONT_SMALL,
                         text=f"{self._span_m:.1f} m across · scroll to zoom")

    def _on_wheel(self, event: tk.Event) -> None:
        factor = 0.85 if event.delta > 0 else 1 / 0.85
        low, high = SPAN_LIMITS_M
        self._span_m = max(low, min(high, self._span_m * factor))
        self._redraw()
