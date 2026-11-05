"""Tuning page: steering PID, speed limits and other robot parameters."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from common.config import TUNING_FIELDS
from station import theme
from station.widgets import Card, NumberRow


class TuningTab(ttk.Frame):
    """Edits the ``tuning`` section. Changes apply live, even while enabled."""

    def __init__(self, parent: tk.Misc, apply: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent, padding=16)
        self._apply_callback = apply
        self._config: Optional[dict[str, Any]] = None
        self._dirty = False
        self._loading = False
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)  # keeps the right-hand cards stacked at the top

        card = Card(self, "Steering and speed")
        card.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        self._rows: dict[str, NumberRow] = {}
        for index, field in enumerate(TUNING_FIELDS):
            row = NumberRow(card, field.label, field.minimum, field.maximum, field.default, field.resolution,
                            field.unit, on_change=lambda _value: self._on_edit())
            row.grid(row=1 + index * 2, column=0, sticky="ew", pady=(6, 0))
            ttk.Label(card, text=field.help, style="CardMuted.TLabel").grid(row=2 + index * 2, column=0,
                                                                           sticky="w", padx=(2, 0))
            self._rows[field.key] = row

        options = Card(self, "Options")
        options.grid(row=0, column=1, sticky="new")
        self._field_relative = tk.BooleanVar(value=False)
        check = ttk.Checkbutton(options, text="Field-relative driving", variable=self._field_relative,
                                style="Card.TCheckbutton")
        check.grid(row=1, column=0, sticky="w")
        check.state(["disabled"])
        ttk.Label(options, text="Needs the MPU-6050, which is not implemented yet.",
                  style="CardMuted.TLabel").grid(row=2, column=0, sticky="w")

        guide = Card(self, "Tuning order")
        guide.grid(row=1, column=1, sticky="new", pady=(12, 0))
        steps = ("1. Wheels off the ground. Raise kP until a wheel snaps to new angles; back off if it oscillates.",
                 "2. Add a little kD to stop overshoot. Leave kI at 0 unless wheels stop short.",
                 "3. Measure top speed (full drive, time a known distance) and enter it as max wheel speed.",
                 "4. On the floor, lower the acceleration limit if the robot jerks.",
                 "Changes apply live, even while enabled.")
        for index, text in enumerate(steps):
            ttk.Label(guide, text=text, style="Card.TLabel", wraplength=480, justify="left").grid(
                row=1 + index, column=0, sticky="w", pady=2)

        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self._status = ttk.Label(footer, text="Waiting for the robot's configuration...", style="Muted.TLabel")
        self._status.grid(row=0, column=0, sticky="w")
        self._revert_button = ttk.Button(footer, text="Revert", command=self._revert)
        self._revert_button.grid(row=0, column=1, padx=6)
        self._apply_button = ttk.Button(footer, text="Apply to robot", style="Accent.TButton", command=self._apply)
        self._apply_button.grid(row=0, column=2)
        self._can_apply = False
        self._refresh_buttons()

    def load(self, config: dict[str, Any]) -> None:
        self._config = config
        if self._dirty:
            return
        self._loading = True
        for key, row in self._rows.items():
            row.set(config["tuning"][key], notify=False)
        self._field_relative.set(config["field_relative"])
        self._loading = False
        self._status.configure(text="Showing the robot's current tuning.", foreground=theme.MUTED)
        self._refresh_buttons()

    def set_can_apply(self, can_apply: bool) -> None:
        self._can_apply = can_apply
        self._refresh_buttons()

    def show_result(self, ok: bool, message: str, errors: list[str]) -> None:
        if ok:
            self._dirty = False
            self._status.configure(text=message, foreground=theme.OK)
        else:
            self._status.configure(text="  ".join([message, *errors]), foreground=theme.ERROR)
        self._refresh_buttons()

    def _on_edit(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self._status.configure(text="Unsaved changes.", foreground=theme.WARN)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        ready = self._dirty and self._config is not None
        self._revert_button.state(["!disabled"] if ready else ["disabled"])
        self._apply_button.state(["!disabled"] if ready and self._can_apply else ["disabled"])

    def _revert(self) -> None:
        self._dirty = False
        if self._config is not None:
            self.load(self._config)

    def _apply(self) -> None:
        update = {"tuning": {key: row.get() for key, row in self._rows.items()}}
        if self._apply_callback(update):
            self._status.configure(text="Sent to the robot...", foreground=theme.MUTED)
        else:
            self.show_result(False, "Not connected to the robot.", [])
