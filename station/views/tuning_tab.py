"""Tuning page: steering PID, speed limits and other robot parameters."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from common.config import TUNING_FIELDS
from station import theme
from station.widgets import Card, NumberRow


class TuningTab(ttk.Frame):
    """Edits the ``tuning`` section.

    Every change is sent to the robot, which applies it live (even while
    enabled) and saves it to its config file straight away. While a slider is
    being dragged, sends are batched to at most one per ``SEND_INTERVAL_MS``;
    the last value is always sent.
    """

    SEND_INTERVAL_MS = 100

    def __init__(self, parent: tk.Misc, apply: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent, padding=16)
        self._apply_callback = apply
        self._config: Optional[dict[str, Any]] = None
        self._loading = False
        self._status_color = theme.MUTED
        self._connected = False
        self._send_job: Optional[str] = None
        self._awaiting = 0   # changes sent but not yet confirmed
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
                 "Each change applies live, even while enabled, and is saved on the robot at once.")
        for index, text in enumerate(steps):
            ttk.Label(guide, text=text, style="Card.TLabel", wraplength=480, justify="left").grid(
                row=1 + index, column=0, sticky="w", pady=2)

        self._status = ttk.Label(self, text="Waiting for the robot's configuration...", style="Muted.TLabel")
        self._status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self._refresh_inputs()

    def load(self, config: dict[str, Any]) -> None:
        """Show the robot's tuning, unless a change of ours is still on its way."""
        self._config = config
        if self._send_job is not None or self._awaiting:
            return
        self._loading = True
        for key, row in self._rows.items():
            row.set(config["tuning"][key], notify=False)
        self._field_relative.set(config["field_relative"])
        self._loading = False
        if self._status_color != theme.OK:  # keep "Saved at ..." visible
            self._set_status("Showing the robot's saved tuning.", theme.MUTED)
        self._refresh_inputs()

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        self._refresh_inputs()
        if not connected:
            self._set_status("Not connected to the robot: tuning can't be changed.", theme.MUTED)

    def show_result(self, ok: bool, message: str, errors: list[str]) -> None:
        self._awaiting = max(0, self._awaiting - 1)
        if ok:
            if not self._awaiting and self._send_job is None:
                self._set_status(f"Saved on the robot at {time.strftime('%H:%M:%S')}.", theme.OK)
            return
        self._set_status("  ".join([f"Not saved: {message}", *errors]), theme.ERROR)
        self._awaiting = 0
        if self._config is not None:
            self.load(self._config)

    def _set_status(self, text: str, color: str) -> None:
        self._status_color = color
        self._status.configure(text=text, foreground=color)

    def _refresh_inputs(self) -> None:
        editable = self._connected and self._config is not None
        for row in self._rows.values():
            row.set_enabled(editable)

    def _on_edit(self) -> None:
        if self._loading or self._config is None:
            return
        self._set_status("Saving...", theme.MUTED)
        if self._send_job is None:
            self._send_job = self.after(self.SEND_INTERVAL_MS, self._send)

    def _send(self) -> None:
        self._send_job = None
        update = {"tuning": {key: row.get() for key, row in self._rows.items()}}
        if self._apply_callback(update):
            self._awaiting += 1
        else:
            self._set_status("Not saved: not connected to the robot.", theme.ERROR)
            if self._config is not None:
                self.load(self._config)
