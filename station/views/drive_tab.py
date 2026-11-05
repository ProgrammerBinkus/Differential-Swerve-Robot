"""Main driver station page: robot view, controls, stick settings and the robot terminal."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Optional

from station.parts import PartInfo
from station.settings import StationSettings
from station.views.robot_view import RobotView
from station.widgets import Card, NumberRow, Terminal


@dataclass
class DriveTabActions:
    toggle_enable: Callable[[], None]
    set_zero: Callable[[], None]
    return_to_zero: Callable[[], None]
    select_part: Callable[[Optional[str]], None]
    settings_changed: Callable[[], None]


class DriveTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, settings: StationSettings, actions: DriveTabActions) -> None:
        super().__init__(parent, padding=12)
        self._settings = settings
        self._actions = actions
        # Layout: part info | robot view | controls, with the terminal across the bottom.
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=3)
        self.rowconfigure(1, weight=1)

        self._build_part_panel(self).grid(row=0, column=0, sticky="nsew")

        self.robot_view = RobotView(self, on_select=actions.select_part)
        self.robot_view.grid(row=0, column=1, sticky="nsew", padx=12)

        side = ttk.Frame(self)
        side.grid(row=0, column=2, sticky="nsew")
        side.columnconfigure(0, weight=1)
        self._build_controls(side).grid(row=0, column=0, sticky="ew")
        self._build_sticks(side).grid(row=1, column=0, sticky="ew", pady=(12, 0))

        self._build_terminal(self).grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(12, 0))

    # ---------------------------------------------------------------- builders

    def _build_controls(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Robot control")
        # takefocus=False: the space bar must only ever disable, never press this button.
        self._enable_button = ttk.Button(card, text="ENABLE", style="Enable.TButton", takefocus=False,
                                         command=self._actions.toggle_enable)
        self._enable_button.grid(row=1, column=0, sticky="ew")
        self._mode_label = ttk.Label(card, text="", style="CardMuted.TLabel")
        self._mode_label.grid(row=2, column=0, sticky="w", pady=(6, 8))
        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.grid(row=3, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1)
        self._zero_button = ttk.Button(buttons, text="Swerve Set Zero  (−)", command=self._actions.set_zero)
        self._zero_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._home_button = ttk.Button(buttons, text="Return to Zero  (+)", command=self._actions.return_to_zero)
        self._home_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Label(card, text="Space bar disables at any time. Press Return to Zero before switching off.",
                  style="CardMuted.TLabel", wraplength=360).grid(row=4, column=0, sticky="w", pady=(8, 0))
        return card

    def _build_sticks(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Joysticks")
        self._input_label = ttk.Label(card, text="", style="CardMuted.TLabel", font=("Cascadia Mono", 9))
        self._input_label.grid(row=1, column=0, sticky="w", pady=(0, 6))
        s = self._settings
        rows = (
            ("Drive sensitivity (left)", "drive_sensitivity", 0.0, 100.0, 1.0, "%"),
            ("Drive deadzone (left)", "drive_deadzone", 0.0, 50.0, 0.5, "%"),
            ("Turn sensitivity (right)", "turn_sensitivity", 0.0, 100.0, 1.0, "%"),
            ("Turn deadzone (right)", "turn_deadzone", 0.0, 50.0, 0.5, "%"),
        )
        for index, (label, key, low, high, step, unit) in enumerate(rows):
            row = NumberRow(card, label, low, high, getattr(s, key), step, unit,
                            on_change=lambda value, key=key: self._on_setting(key, value))
            row.grid(row=2 + index, column=0, sticky="ew", pady=3)
        return card

    def _build_part_panel(self, parent: tk.Misc) -> Card:
        card = Card(parent, "Part info")
        card.rowconfigure(3, weight=1)
        # A fixed width keeps the robot view from shifting as the text changes.
        ttk.Frame(card, style="Card.TFrame", width=270, height=1).grid(row=4, column=0)
        self._part_title = ttk.Label(card, text="Click any part or module", style="CardBold.TLabel",
                                     wraplength=270)
        self._part_title.grid(row=1, column=0, sticky="w")
        self._part_subtitle = ttk.Label(card, text="", style="CardMuted.TLabel", wraplength=270)
        self._part_subtitle.grid(row=2, column=0, sticky="w", pady=(2, 6))
        self._part_body = ttk.Label(card, text="", style="Card.TLabel", wraplength=270, justify="left")
        self._part_body.grid(row=3, column=0, sticky="nw")
        return card

    def _build_terminal(self, parent: tk.Misc) -> Card:
        card = Card(parent, padding=10)
        card.rowconfigure(1, weight=1)
        header = ttk.Frame(card, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Robot terminal", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        self.show_telemetry = tk.BooleanVar(value=False)
        ttk.Checkbutton(header, text="Show telemetry (2 Hz)", variable=self.show_telemetry,
                        style="Card.TCheckbutton").grid(row=0, column=1, padx=8)
        self.terminal = Terminal(card)
        ttk.Button(header, text="Clear", command=self.terminal.clear).grid(row=0, column=2)
        self.terminal.grid(row=1, column=0, sticky="nsew")
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
        self._zero_button.state(["!disabled"] if robot_ready else ["disabled"])
        self._home_button.state(["!disabled"] if enabled else ["disabled"])

    def show_inputs(self, vx: float, vy: float, omega: float) -> None:
        self._input_label.configure(text=f"forward {vx:+.2f}   left {vy:+.2f}   turn {omega:+.2f}")

    def show_part(self, info: Optional[PartInfo]) -> None:
        if info is None:
            self._part_title.configure(text="Click any part or module")
            self._part_subtitle.configure(text="")
            self._part_body.configure(text="")
            return
        self._part_title.configure(text=info.title)
        self._part_subtitle.configure(text=info.subtitle)
        facts = "\n".join(info.lines)
        self._part_body.configure(text=f"{info.note}\n\n{facts}" if info.note else facts)
