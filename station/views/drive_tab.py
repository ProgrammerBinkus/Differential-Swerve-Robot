"""Main driver station page: part info, the plan-view drawing, controls and the robot terminal."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Optional

from station import theme
from station.keyboard import KEYMAP, key_label
from station.parts import WIRE_LAYERS, PartInfo
from station.settings import StationSettings
from station.views.robot_view import LAYER_COLORS, RobotView
from station.widgets import Card, Keycap, NumberRow, Segmented, Terminal, ToggleSwitch

PANEL_TEXT_WIDTH = 270

# "Robot faces ..." choices for Set field forward, in degrees from "away from the driver station"
# (counter-clockwise positive, as seen from above).
FACINGS = (("away", "Away", 0.0), ("left", "Left", 90.0), ("toward", "Toward", 180.0), ("right", "Right", -90.0))


@dataclass
class DriveTabActions:
    toggle_enable: Callable[[], None]
    set_zero: Callable[[], None]
    return_to_zero: Callable[[], None]
    select_part: Callable[[Optional[str]], None]
    settings_changed: Callable[[], None]
    keyboard_toggled: Callable[[bool], None]
    field_toggled: Callable[[bool], None]
    set_field_forward: Callable[[float], None]


class LayerChip(tk.Frame):
    """A toggle showing one harness layer's color, like the wiring sheet's layer buttons."""

    def __init__(self, parent: tk.Misc, text: str, color: str, on_toggle: Callable[[bool], None]) -> None:
        super().__init__(parent, bg=theme.FIELD, highlightthickness=1, highlightbackground=theme.RULE,
                         cursor="hand2", padx=7, pady=3)
        self._color = color
        self._on = True
        self._on_toggle = on_toggle
        self._swatch = tk.Frame(self, width=14, height=4, bg=color)
        self._swatch.pack(side="left", padx=(0, 6))
        self._label = tk.Label(self, text=text, bg=theme.FIELD, fg=theme.INK, font=theme.FONT_SMALL)
        self._label.pack(side="left")
        for widget in (self, self._swatch, self._label):
            widget.bind("<Button-1>", self._toggle)

    def _toggle(self, _event: tk.Event) -> None:
        self._on = not self._on
        self._swatch.configure(bg=self._color if self._on else theme.RULE)
        self._label.configure(fg=theme.INK if self._on else theme.MUTED)
        self._on_toggle(self._on)


class DriveTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, settings: StationSettings, actions: DriveTabActions) -> None:
        super().__init__(parent, padding=(16, 14, 16, 16))
        self._settings = settings
        self._actions = actions
        # Layout, all full height:
        #   part info + robot terminal | drawing | robot control + joysticks and keyboard
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        self._build_part_panel(left).grid(row=0, column=0, sticky="nsew")
        self._build_field(left).grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self._build_terminal(left).grid(row=2, column=0, sticky="nsew", pady=(14, 0))

        self._build_figure(self).grid(row=0, column=1, sticky="nsew", padx=14)

        side = ttk.Frame(self)
        side.grid(row=0, column=2, sticky="nsew")
        side.columnconfigure(0, weight=1)
        self._build_controls(side).grid(row=0, column=0, sticky="ew")
        self._build_sticks(side).grid(row=1, column=0, sticky="ew", pady=(14, 0))

    # ---------------------------------------------------------------- builders

    def _build_figure(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=theme.INK, padx=1, pady=1)  # the drawing's ink border
        inner = tk.Frame(frame, bg=theme.SHEET)
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(2, weight=1)

        toolbar = tk.Frame(inner, bg=theme.SHEET, padx=12, pady=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        tk.Label(toolbar, text="LAYERS", bg=theme.SHEET, fg=theme.MUTED, font=theme.FONT_LABEL).pack(
            side="left", padx=(0, 10))
        for layer, label in reversed(WIRE_LAYERS):  # power first, as on the sheet
            LayerChip(toolbar, label, LAYER_COLORS[layer],
                      lambda on, layer=layer: self.robot_view.set_layer_visible(layer, on)).pack(side="left", padx=2)
        tk.Frame(inner, height=1, bg=theme.RULE).grid(row=1, column=0, sticky="ew")

        self.robot_view = RobotView(inner, on_select=self._actions.select_part)
        self.robot_view.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)

        tk.Frame(inner, height=1, bg=theme.RULE).grid(row=3, column=0, sticky="ew")
        tk.Label(inner, text="Plan view, front at top  ·  wheel = reported angle  ·  dashed = target  ·  "
                             "arrow = drive",
                 bg=theme.SHEET, fg=theme.MUTED, font=theme.FONT_SMALL, anchor="w", padx=12, pady=6).grid(
            row=4, column=0, sticky="ew")
        return frame

    def _build_part_panel(self, parent: tk.Misc) -> Card:
        card = Card(parent, padding=16)
        # A fixed-width strut keeps the drawing from shifting as the text changes.
        ttk.Frame(card, style="Plain.TFrame", width=PANEL_TEXT_WIDTH, height=1).grid(row=7, column=0)
        self._part_kind = ttk.Label(card, text="", style="CardLabel.TLabel")
        self._part_kind.grid(row=0, column=0, sticky="w")
        self._part_title = ttk.Label(card, text="", style="CardHeading.TLabel", wraplength=PANEL_TEXT_WIDTH)
        self._part_title.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._part_subtitle = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=PANEL_TEXT_WIDTH,
                                        justify="left")
        self._part_subtitle.grid(row=2, column=0, sticky="w", pady=(2, 10))
        self._part_note = ttk.Label(card, text="", style="Card.TLabel", wraplength=PANEL_TEXT_WIDTH, justify="left")
        self._part_note.grid(row=3, column=0, sticky="w")
        self._part_rule = tk.Frame(card, height=1, bg=theme.RULE)
        self._part_rule.grid(row=4, column=0, sticky="ew", pady=10)
        self._part_facts = ttk.Label(card, text="", style="Card.TLabel", wraplength=PANEL_TEXT_WIDTH, justify="left")
        self._part_facts.grid(row=5, column=0, sticky="nw")

        self._legend = ttk.Frame(card, style="Plain.TFrame")
        for row, (layer, label) in enumerate(reversed(WIRE_LAYERS)):
            tk.Frame(self._legend, width=18, height=4, bg=LAYER_COLORS[layer]).grid(row=row, column=0, padx=(0, 10))
            ttk.Label(self._legend, text=label, style="Card.TLabel").grid(row=row, column=1, sticky="w", pady=2)
        self.show_part(None)
        return card

    def _build_field(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Field-relative drive")
        top = ttk.Frame(card, style="Plain.TFrame")
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        self._field_switch = ToggleSwitch(top, "Field-relative", False, self._actions.field_toggled)
        self._field_switch.grid(row=0, column=0, sticky="w")
        self._heading_label = tk.Label(top, text="—", bg=theme.SHEET, fg=theme.MUTED, font=(theme.MONO, 12))
        self._heading_label.grid(row=0, column=1, sticky="e")
        self._field_status = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=PANEL_TEXT_WIDTH,
                                       justify="left")
        self._field_status.grid(row=2, column=0, sticky="w", pady=(6, 10))

        ttk.Label(card, text="ROBOT FACES (FROM WHERE YOU STAND)", style="CardLabel.TLabel").grid(
            row=3, column=0, sticky="w")
        self._facings = {key: degrees for key, _label, degrees in FACINGS}
        self._facing_switch = Segmented(card, tuple((key, label) for key, label, _ in FACINGS), "away",
                                        lambda key: self._facing_switch.set(key))
        self._facing_switch.grid(row=4, column=0, sticky="w", pady=(4, 8))
        self._field_button = ttk.Button(card, text="Set field forward", command=self._set_field_forward)
        self._field_button.grid(row=5, column=0, sticky="ew")
        ttk.Label(card, text="Sets \"forward\" to away from the laptop. Point the robot, pick which way it "
                             "faces as seen from the laptop, then press it.",
                  style="CardMuted.TLabel", wraplength=PANEL_TEXT_WIDTH, justify="left").grid(
            row=6, column=0, sticky="w", pady=(6, 0))
        self.show_field(None, connected=False, imu=None)
        return card

    def _set_field_forward(self) -> None:
        self._actions.set_field_forward(self._facings[self._facing_switch.value])

    def _build_controls(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Robot control")
        # takefocus=False: the space bar must only ever disable, never press this button.
        self._enable_button = ttk.Button(card, text="ENABLE", style="Enable.TButton", takefocus=False,
                                         command=self._actions.toggle_enable)
        self._enable_button.grid(row=1, column=0, sticky="ew")
        self._mode_label = ttk.Label(card, text="", style="CardMuted.TLabel")
        self._mode_label.grid(row=2, column=0, sticky="w", pady=(6, 10))
        buttons = ttk.Frame(card, style="Plain.TFrame")
        buttons.grid(row=3, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1, uniform="buttons")
        self._zero_button = ttk.Button(buttons, text="Swerve Set Zero  −", command=self._actions.set_zero)
        self._zero_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._home_button = ttk.Button(buttons, text="Return to Zero  +", command=self._actions.return_to_zero)
        self._home_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Label(card, text="Space disables at any time. Set Zero works while disabled; "
                             "Return to Zero before switching off.",
                  style="CardMuted.TLabel", wraplength=360).grid(row=4, column=0, sticky="w", pady=(10, 0))
        return card

    def _build_sticks(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Joysticks")
        readout = tk.Frame(card, bg=theme.RULE, padx=1, pady=1)
        readout.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._readouts: dict[str, tk.Label] = {}
        for column, key in enumerate(("forward", "left", "turn")):
            readout.columnconfigure(column, weight=1, uniform="readout")
            cell = tk.Frame(readout, bg=theme.FIELD, padx=10, pady=5)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 1, 0))
            tk.Label(cell, text=key.upper(), bg=theme.FIELD, fg=theme.MUTED, font=theme.FONT_LABEL).pack(anchor="w")
            self._readouts[key] = tk.Label(cell, text="+0.00", bg=theme.FIELD, fg=theme.INK,
                                           font=(theme.MONO, 12))
            self._readouts[key].pack(anchor="w")
        rows = (  # the left stick drives, the right stick turns
            ("Drive sensitivity", "drive_sensitivity", 0.0, 100.0, 1.0, "%"),
            ("Drive deadzone", "drive_deadzone", 0.0, 50.0, 0.5, "%"),
            ("Turn sensitivity", "turn_sensitivity", 0.0, 100.0, 1.0, "%"),
            ("Turn deadzone", "turn_deadzone", 0.0, 50.0, 0.5, "%"),
        )
        for index, (label, key, low, high, step, unit) in enumerate(rows):
            row = NumberRow(card, label, low, high, getattr(self._settings, key), step, unit,
                            on_change=lambda value, key=key: self._on_setting(key, value), label_width=16,
                            unit_width=2)
            row.grid(row=2 + index, column=0, sticky="ew", pady=4)
        self._build_keyboard(card).grid(row=6, column=0, sticky="ew", pady=(10, 0))
        return card

    def _build_keyboard(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Plain.TFrame")
        frame.columnconfigure(0, weight=1)
        tk.Frame(frame, height=1, bg=theme.RULE).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header = ttk.Frame(frame, style="Plain.TFrame")
        header.grid(row=1, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self._keyboard_switch = ToggleSwitch(header, "Keyboard control", self._settings.keyboard_control,
                                             self._actions.keyboard_toggled)
        self._keyboard_switch.grid(row=0, column=0, sticky="w")
        self._keyboard_hint = ttk.Label(header, text="", style="CardMuted.TLabel")
        self._keyboard_hint.grid(row=0, column=1, sticky="e")

        # The keymap, two actions per row: forward/back, strafe left/right, turn left/right.
        self._keymap = ttk.Frame(frame, style="Plain.TFrame")
        self._keycaps: dict[str, list[Keycap]] = {}
        for index, (action, label, keys) in enumerate(KEYMAP):
            row, column = divmod(index, 2)
            cell = ttk.Frame(self._keymap, style="Plain.TFrame")
            cell.grid(row=row, column=column, sticky="w", padx=(0, 18), pady=2)
            caps = ttk.Frame(cell, style="Plain.TFrame", width=64)
            caps.pack(side="left")
            self._keycaps[action] = []
            for key in keys:
                cap = Keycap(caps, key_label(key))
                cap.pack(side="left", padx=(0, 3))
                self._keycaps[action].append(cap)
            ttk.Label(cell, text=label, style="Card.TLabel").pack(side="left", padx=(4, 0))
        self.show_keyboard(self._settings.keyboard_control, paused=False)
        return frame

    def _build_terminal(self, parent: tk.Misc) -> Card:
        card = Card(parent, padding=(14, 10, 14, 14))
        card.rowconfigure(2, weight=1)
        header = ttk.Frame(card, style="Plain.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="ROBOT TERMINAL", style="CardLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.show_telemetry = tk.BooleanVar(value=False)
        ttk.Checkbutton(header, text="Show telemetry", variable=self.show_telemetry,
                        style="Card.TCheckbutton").grid(row=0, column=1, padx=12)
        self.terminal = Terminal(card)
        ttk.Button(header, text="Clear", command=self.terminal.clear).grid(row=0, column=2)
        tk.Frame(card, height=1, bg=theme.RULE).grid(row=1, column=0, sticky="ew", pady=(8, 10))
        self.terminal.grid(row=2, column=0, sticky="nsew")
        return card

    # ------------------------------------------------------------------ update

    def _on_setting(self, key: str, value: float) -> None:
        setattr(self._settings, key, value)
        self._actions.settings_changed()

    def show_state(self, enabled: bool, can_enable: bool, mode: str, robot_ready: bool) -> None:
        if enabled:
            self._enable_button.configure(text="DISABLE", style="Disable.TButton")
            self._enable_button.state(["!disabled"])
        else:
            self._enable_button.configure(text="ENABLE", style="Enable.TButton")
            self._enable_button.state(["!disabled"] if can_enable else ["disabled"])
        self._mode_label.configure(text=mode)
        self._zero_button.state(["!disabled"] if robot_ready and not enabled else ["disabled"])
        self._home_button.state(["!disabled"] if enabled else ["disabled"])

    def show_field(self, field_relative: Optional[bool], connected: bool, imu: Optional[dict],
                   update_switch: bool = True) -> None:
        """Show the robot's field-relative setting and IMU state (``None`` while not connected)."""
        if update_switch:
            self._field_switch.set(bool(field_relative))
        self._field_switch.set_enabled(connected and field_relative is not None)
        status = (imu or {}).get("status")
        heading = (imu or {}).get("heading")
        self._heading_label.configure(text="—" if heading is None else f"{round(heading):+d}°",  # never "-0°"
                                      fg=theme.INK if heading is not None else theme.MUTED)
        if not connected or imu is None:
            text, color = "Robot not connected.", theme.MUTED
        elif status == "absent":
            text, color = "No IMU found: driving robot-relative.", theme.WARN
        elif status == "fault":
            text, color = "IMU not answering: driving robot-relative.", theme.ERROR
        elif status == "calibrating":
            text, color = "Gyro calibrating. Keep the robot still.", theme.WARN
        elif field_relative:
            text, color = "On: stick forward drives away from the laptop.", theme.OK
        else:
            text, color = "Off: stick forward drives the robot's front forward.", theme.MUTED
        self._field_status.configure(text=text, foreground=color)
        self._field_button.state(["!disabled"] if connected and status == "ok" else ["disabled"])

    def show_keyboard(self, on: bool, paused: bool) -> None:
        """Show or hide the keymap, and say when keys are paused."""
        self._keyboard_switch.set(on)
        if on:
            self._keymap.grid(row=2, column=0, sticky="w", pady=(8, 0))
            self._keyboard_hint.configure(text="Paused while typing. Click the drawing to drive." if paused else "")
        else:
            self._keymap.grid_remove()
            self._keyboard_hint.configure(text="")

    def show_held_keys(self, actions: set[str]) -> None:
        for action, caps in self._keycaps.items():
            for cap in caps:
                cap.set_active(action in actions)

    def show_inputs(self, vx: float, vy: float, omega: float) -> None:
        for key, value in (("forward", vx), ("left", vy), ("turn", omega)):
            active = abs(value) >= 0.005
            self._readouts[key].configure(text=f"{value:+.2f}" if active else " 0.00",
                                          fg=theme.INK if active else theme.MUTED)

    def show_part(self, info: Optional[PartInfo]) -> None:
        if info is None:
            self._part_kind.configure(text="TRACE A CONNECTION")
            self._part_title.configure(text="Click any part")
            self._part_subtitle.configure(text="The drawing fades everything not connected to it. "
                                               "Click a module for its live angle and motor commands.")
            self._part_note.configure(text="")
            self._part_facts.configure(text="")
            self._part_rule.grid_remove()
            self._legend.grid(row=5, column=0, sticky="nw")
            return
        self._legend.grid_remove()
        self._part_rule.grid()
        self._part_kind.configure(text=info.kind.upper())
        self._part_title.configure(text=info.title)
        self._part_subtitle.configure(text=info.subtitle)
        self._part_note.configure(text=info.note)
        if info.note:
            self._part_note.grid()
        else:
            self._part_note.grid_remove()
        self._part_facts.configure(text="\n".join(info.lines))
