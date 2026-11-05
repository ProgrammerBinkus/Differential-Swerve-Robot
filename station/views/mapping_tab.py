"""Mapping page: which motors, encoders and H-bridge channels belong to each module."""

from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from common.config import (
    ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS, MODULE_NAMES, MOTOR_IDS, ConfigError, merge_config,
    validate_config,
)
from station import theme
from station.widgets import Card

_MODULE_KEYS = ("motor_a", "invert_a", "motor_b", "invert_b", "encoder", "invert_encoder")


def mapping_of(config: dict[str, Any]) -> dict[str, Any]:
    """The part of a config this page edits, in the shape it sends."""
    return {
        "modules": {name: {key: config["modules"][name][key] for key in _MODULE_KEYS} for name in MODULE_NAMES},
        "motors": {motor_id: {"hbridge": config["motors"][motor_id]["hbridge"],
                              "channel": config["motors"][motor_id]["channel"]} for motor_id in MOTOR_IDS},
        "encoders": {encoder_id: {"bus": config["encoders"][encoder_id]["bus"]} for encoder_id in ENCODER_IDS},
    }


class MappingTab(ttk.Frame):
    """Edits the ``modules``, ``motors`` and ``encoders`` sections of the robot config.

    Every change is checked with the same validation the robot runs and, if
    the mapping is complete and valid, sent at once; the robot applies it and
    saves it to its config file. A half-finished edit (say, a motor briefly
    used twice while two are being swapped) waits until it is valid. Bus paths
    are sent when you press Enter or leave the box, not on every keystroke.
    The robot only accepts mapping changes while disabled.
    """

    def __init__(self, parent: tk.Misc, apply: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent, padding=16)
        self._apply_callback = apply
        self._config: Optional[dict[str, Any]] = None
        self._loading = False
        self._status_color = theme.MUTED
        self._can_apply = False
        self._reason = ""
        self._incomplete = False   # the widgets hold a mapping that is not valid yet
        self._awaiting = 0         # changes sent but not yet confirmed
        self.columnconfigure((0, 1), weight=1)

        intro = ("Match the software to the real wiring. Run the motor test from the README first, "
                 "then set the invert flags so that a positive drive rolls each wheel forward and a "
                 "positive steer turns it counter-clockwise. Re-run Swerve Set Zero after changing an encoder. "
                 "Each change is saved on the robot as soon as you make it.")
        ttk.Label(self, text=intro, style="Muted.TLabel", wraplength=1100, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self._module_vars: dict[str, dict[str, tk.Variable]] = {}
        self._motor_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._encoder_vars: dict[str, tk.StringVar] = {}
        self._inputs: list[ttk.Widget] = []

        self._build_modules().grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_motors().grid(row=2, column=0, sticky="nsew", pady=12, padx=(0, 6))
        self._build_encoders().grid(row=2, column=1, sticky="nsew", pady=12, padx=(6, 0))

        self._status = ttk.Label(self, text="Waiting for the robot's configuration...", style="Muted.TLabel",
                                 wraplength=1100, justify="left")
        self._status.grid(row=3, column=0, columnspan=2, sticky="w")
        self._refresh_inputs()

    # ---------------------------------------------------------------- builders

    def _combo(self, parent: tk.Misc, variable: tk.StringVar, values: tuple[str, ...], width: int = 8) -> ttk.Combobox:
        box = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        self._inputs.append(box)
        return box

    def _check(self, parent: tk.Misc, variable: tk.BooleanVar) -> ttk.Checkbutton:
        box = ttk.Checkbutton(parent, variable=variable, style="Card.TCheckbutton")
        self._inputs.append(box)
        return box

    @staticmethod
    def _headers(table: ttk.Frame, headers: tuple[str, ...]) -> None:
        for column, text in enumerate(headers):
            ttk.Label(table, text=text.upper(), style="CardLabel.TLabel").grid(
                row=0, column=column, padx=10, pady=(0, 4), sticky="w")

    def _build_modules(self) -> Card:
        card = Card(self, "Modules")
        table = ttk.Frame(card, style="Plain.TFrame")
        table.grid(row=1, column=0, sticky="w")
        self._headers(table, ("Module", "Motor A", "Invert A", "Motor B", "Invert B", "Encoder", "Invert encoder",
                              "Zero offset"))
        for row, name in enumerate(MODULE_NAMES, start=1):
            v = {"motor_a": tk.StringVar(), "invert_a": tk.BooleanVar(), "motor_b": tk.StringVar(),
                 "invert_b": tk.BooleanVar(), "encoder": tk.StringVar(), "invert_encoder": tk.BooleanVar(),
                 "offset": tk.StringVar(value="—")}
            self._module_vars[name] = v
            ttk.Label(table, text=name, style="CardBold.TLabel").grid(row=row, column=0, padx=10, pady=3, sticky="w")
            self._combo(table, v["motor_a"], MOTOR_IDS).grid(row=row, column=1, padx=10)
            self._check(table, v["invert_a"]).grid(row=row, column=2, padx=10)
            self._combo(table, v["motor_b"], MOTOR_IDS).grid(row=row, column=3, padx=10)
            self._check(table, v["invert_b"]).grid(row=row, column=4, padx=10)
            self._combo(table, v["encoder"], ENCODER_IDS).grid(row=row, column=5, padx=10)
            self._check(table, v["invert_encoder"]).grid(row=row, column=6, padx=10)
            ttk.Label(table, textvariable=v["offset"], style="Card.TLabel").grid(row=row, column=7, padx=10, sticky="w")
            for key in _MODULE_KEYS:
                v[key].trace_add("write", self._on_change)
        return card

    def _build_motors(self) -> Card:
        card = Card(self, "Motors → H-bridge channels")
        table = ttk.Frame(card, style="Plain.TFrame")
        table.grid(row=1, column=0, sticky="w")
        self._headers(table, ("Motor", "H-bridge", "Channel"))
        for row, motor_id in enumerate(MOTOR_IDS, start=1):
            v = {"hbridge": tk.StringVar(), "channel": tk.StringVar()}
            self._motor_vars[motor_id] = v
            ttk.Label(table, text=motor_id, style="CardBold.TLabel").grid(row=row, column=0, padx=10, pady=3, sticky="w")
            self._combo(table, v["hbridge"], HBRIDGE_IDS).grid(row=row, column=1, padx=10)
            self._combo(table, v["channel"], HBRIDGE_CHANNELS, width=4).grid(row=row, column=2, padx=10)
            for var in v.values():
                var.trace_add("write", self._on_change)
        return card

    def _build_encoders(self) -> Card:
        card = Card(self, "Encoders → I2C buses")
        table = ttk.Frame(card, style="Plain.TFrame")
        table.grid(row=1, column=0, sticky="w")
        self._headers(table, ("Encoder", "Linux bus", "Header pins"))
        self._pin_labels: dict[str, ttk.Label] = {}
        for row, encoder_id in enumerate(ENCODER_IDS, start=1):
            var = tk.StringVar()
            self._encoder_vars[encoder_id] = var
            ttk.Label(table, text=encoder_id, style="CardBold.TLabel").grid(row=row, column=0, padx=10, pady=3, sticky="w")
            entry = ttk.Entry(table, textvariable=var, width=14, font=theme.FONT_MONO)
            entry.grid(row=row, column=1, padx=10)
            entry.bind("<Return>", self._on_change)
            entry.bind("<FocusOut>", self._on_change)
            self._inputs.append(entry)
            self._pin_labels[encoder_id] = ttk.Label(table, text="", style="CardMuted.TLabel")
            self._pin_labels[encoder_id].grid(row=row, column=2, padx=10, sticky="w")
        ttk.Label(card, text="Every MT6701 answers at 0x06, so each needs its own bus. "
                             "Run `i2cdetect -l` on the Pi to see the bus numbers. Press Enter to save a bus.",
                  style="CardMuted.TLabel", wraplength=480, justify="left").grid(row=2, column=0, sticky="w",
                                                                                 pady=(8, 0))
        return card

    # ------------------------------------------------------------------ state

    def load(self, config: dict[str, Any]) -> None:
        """Show the robot's configuration, unless the widgets hold an edit that is not finished or not confirmed."""
        self._config = copy.deepcopy(config)
        self._show_offsets(config)
        if self._incomplete or self._awaiting:
            return
        self._loading = True
        for name, v in self._module_vars.items():
            for key in _MODULE_KEYS:
                v[key].set(config["modules"][name][key])
        for motor_id, v in self._motor_vars.items():
            v["hbridge"].set(config["motors"][motor_id]["hbridge"])
            v["channel"].set(config["motors"][motor_id]["channel"])
        for encoder_id, var in self._encoder_vars.items():
            encoder = config["encoders"][encoder_id]
            var.set(encoder["bus"])
            self._pin_labels[encoder_id].configure(
                text=f"{encoder.get('sda_pin', '?')} SDA / {encoder.get('scl_pin', '?')} SCL")
        self._loading = False
        if self._status_color != theme.OK:  # keep "Saved at ..." visible
            self._set_status("Showing the robot's saved mapping.", theme.MUTED)
        self._refresh_inputs()

    def set_can_apply(self, can_apply: bool, reason: str = "") -> None:
        if (can_apply, reason) == (self._can_apply, self._reason):
            return
        self._can_apply, self._reason = can_apply, reason
        self._refresh_inputs()
        if not can_apply and reason:
            self._set_status(reason, theme.MUTED)
        elif can_apply and self._config is not None:
            self._set_status("Ready. Each change is saved on the robot as soon as you make it.", theme.MUTED)

    def show_result(self, ok: bool, message: str, errors: list[str]) -> None:
        self._awaiting = max(0, self._awaiting - 1)
        if ok:
            self._set_status(f"Saved on the robot at {time.strftime('%H:%M:%S')}.", theme.OK)
            return
        self._set_status("\n".join([f"Not saved: {message}", *errors, "Showing the robot's mapping again."]),
                         theme.ERROR)
        self._incomplete = False
        self._awaiting = 0
        if self._config is not None:
            self.load(self._config)

    # --------------------------------------------------------------- editing

    def _set_status(self, text: str, color: str) -> None:
        self._status_color = color
        self._status.configure(text=text, foreground=color)

    def _show_offsets(self, config: dict[str, Any]) -> None:
        for name, v in self._module_vars.items():
            v["offset"].set(str(config["modules"][name]["offset"]))

    def _refresh_inputs(self) -> None:
        editable = self._config is not None and self._can_apply
        for widget in self._inputs:
            if isinstance(widget, ttk.Combobox):
                widget.state(["readonly", "!disabled"] if editable else ["disabled"])
            else:
                widget.state(["!disabled"] if editable else ["disabled"])

    def _collect(self) -> dict[str, Any]:
        modules = {name: {key: v[key].get() for key in _MODULE_KEYS} for name, v in self._module_vars.items()}
        motors = {motor_id: {"hbridge": v["hbridge"].get(), "channel": v["channel"].get()}
                  for motor_id, v in self._motor_vars.items()}
        encoders = {encoder_id: {"bus": var.get().strip()} for encoder_id, var in self._encoder_vars.items()}
        return {"modules": modules, "motors": motors, "encoders": encoders}

    def _on_change(self, *_args: object) -> None:
        if self._loading or self._config is None or not self._can_apply:
            return
        update = self._collect()
        if update == mapping_of(self._config):
            self._incomplete = False
            return  # nothing changed (for example, leaving a bus box without editing it)
        try:
            errors = validate_config(merge_config(self._config, update))
        except ConfigError as exc:
            errors = [str(exc)]
        if errors:
            self._incomplete = True
            self._set_status("\n".join(["Not saved yet, finish the change:", *errors]), theme.WARN)
            return
        self._incomplete = False
        if self._apply_callback(update):
            self._awaiting += 1
            self._set_status("Saving...", theme.MUTED)
        else:
            self._set_status("Not saved: not connected to the robot.", theme.ERROR)
