"""Mapping page: which motors, encoders and H-bridge channels belong to each module."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from common.config import (
    ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS, MODULE_NAMES, MOTOR_IDS, ConfigError, merge_config,
    validate_config,
)
from station import theme
from station.widgets import Card


class MappingTab(ttk.Frame):
    """Edits the ``modules``, ``motors`` and ``encoders`` sections of the robot config.

    Changes are checked locally with the same validation the robot runs, then
    sent with ``apply``. The robot only accepts them while disabled.
    """

    def __init__(self, parent: tk.Misc, apply: Callable[[dict[str, Any]], bool]) -> None:
        super().__init__(parent, padding=16)
        self._apply_callback = apply
        self._config: Optional[dict[str, Any]] = None
        self._dirty = False
        self._loading = False
        self._can_apply = False
        self._apply_reason = ""
        self.columnconfigure((0, 1), weight=1)

        intro = ("Match the software to the real wiring. Run the motor test from the README first, "
                 "then set the invert flags so that a positive drive rolls each wheel forward and a "
                 "positive steer turns it counter-clockwise. Re-run Swerve Set Zero after changing an encoder.")
        ttk.Label(self, text=intro, style="Muted.TLabel", wraplength=1100, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self._module_vars: dict[str, dict[str, tk.Variable]] = {}
        self._motor_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._encoder_vars: dict[str, tk.StringVar] = {}
        self._inputs: list[ttk.Widget] = []

        self._build_modules().grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_motors().grid(row=2, column=0, sticky="nsew", pady=12, padx=(0, 6))
        self._build_encoders().grid(row=2, column=1, sticky="nsew", pady=12, padx=(6, 0))

        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._status = ttk.Label(footer, text="Waiting for the robot's configuration...", style="Muted.TLabel",
                                 wraplength=800, justify="left")
        self._status.grid(row=0, column=0, sticky="w")
        self._revert_button = ttk.Button(footer, text="Revert", command=self._revert)
        self._revert_button.grid(row=0, column=1, padx=6)
        self._apply_button = ttk.Button(footer, text="Apply to robot", style="Accent.TButton", command=self._apply)
        self._apply_button.grid(row=0, column=2)
        self._refresh_buttons()

    # ---------------------------------------------------------------- builders

    def _combo(self, parent: tk.Misc, variable: tk.StringVar, values: tuple[str, ...], width: int = 8) -> ttk.Combobox:
        box = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        self._inputs.append(box)
        return box

    def _check(self, parent: tk.Misc, variable: tk.BooleanVar) -> ttk.Checkbutton:
        box = ttk.Checkbutton(parent, variable=variable, style="Card.TCheckbutton")
        self._inputs.append(box)
        return box

    def _build_modules(self) -> Card:
        card = Card(self, "Modules")
        table = ttk.Frame(card, style="Card.TFrame")
        table.grid(row=1, column=0, sticky="w")
        headers = ("Module", "Motor A", "Invert A", "Motor B", "Invert B", "Encoder", "Invert encoder",
                   "Zero offset")
        for column, text in enumerate(headers):
            ttk.Label(table, text=text, style="CardMuted.TLabel").grid(row=0, column=column, padx=10, pady=(0, 4),
                                                                      sticky="w")
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
            for key, var in v.items():
                if key != "offset":
                    var.trace_add("write", self._on_edit)
        return card

    def _build_motors(self) -> Card:
        card = Card(self, "Motors → H-bridge channels")
        table = ttk.Frame(card, style="Card.TFrame")
        table.grid(row=1, column=0, sticky="w")
        for column, text in enumerate(("Motor", "H-bridge", "Channel")):
            ttk.Label(table, text=text, style="CardMuted.TLabel").grid(row=0, column=column, padx=10, pady=(0, 4),
                                                                      sticky="w")
        for row, motor_id in enumerate(MOTOR_IDS, start=1):
            v = {"hbridge": tk.StringVar(), "channel": tk.StringVar()}
            self._motor_vars[motor_id] = v
            ttk.Label(table, text=motor_id, style="CardBold.TLabel").grid(row=row, column=0, padx=10, pady=3, sticky="w")
            self._combo(table, v["hbridge"], HBRIDGE_IDS).grid(row=row, column=1, padx=10)
            self._combo(table, v["channel"], HBRIDGE_CHANNELS, width=4).grid(row=row, column=2, padx=10)
            for var in v.values():
                var.trace_add("write", self._on_edit)
        return card

    def _build_encoders(self) -> Card:
        card = Card(self, "Encoders → I2C buses")
        table = ttk.Frame(card, style="Card.TFrame")
        table.grid(row=1, column=0, sticky="w")
        for column, text in enumerate(("Encoder", "Linux bus", "Header pins")):
            ttk.Label(table, text=text, style="CardMuted.TLabel").grid(row=0, column=column, padx=10, pady=(0, 4),
                                                                      sticky="w")
        self._pin_labels: dict[str, ttk.Label] = {}
        for row, encoder_id in enumerate(ENCODER_IDS, start=1):
            var = tk.StringVar()
            self._encoder_vars[encoder_id] = var
            ttk.Label(table, text=encoder_id, style="CardBold.TLabel").grid(row=row, column=0, padx=10, pady=3, sticky="w")
            entry = ttk.Entry(table, textvariable=var, width=14)
            entry.grid(row=row, column=1, padx=10)
            self._inputs.append(entry)
            self._pin_labels[encoder_id] = ttk.Label(table, text="", style="CardMuted.TLabel")
            self._pin_labels[encoder_id].grid(row=row, column=2, padx=10, sticky="w")
            var.trace_add("write", self._on_edit)
        ttk.Label(card, text="Every MT6701 answers at 0x06, so each needs its own bus. "
                             "Run `i2cdetect -l` on the Pi to see the bus numbers.",
                  style="CardMuted.TLabel", wraplength=480, justify="left").grid(row=2, column=0, sticky="w",
                                                                                 pady=(8, 0))
        return card

    # ------------------------------------------------------------------ state

    def load(self, config: dict[str, Any]) -> None:
        """Show a configuration from the robot. Unsaved edits are kept until reverted."""
        self._config = copy.deepcopy(config)
        if self._dirty:
            self._status.configure(text="The robot's configuration changed. Revert to load it, or apply your edits.",
                                   foreground=theme.WARN)
            self._show_offsets(config)
            return
        self._loading = True
        for name, v in self._module_vars.items():
            module = config["modules"][name]
            for key, var in v.items():
                if key != "offset":
                    var.set(module[key])
        for motor_id, v in self._motor_vars.items():
            v["hbridge"].set(config["motors"][motor_id]["hbridge"])
            v["channel"].set(config["motors"][motor_id]["channel"])
        for encoder_id, var in self._encoder_vars.items():
            encoder = config["encoders"][encoder_id]
            var.set(encoder["bus"])
            self._pin_labels[encoder_id].configure(
                text=f"{encoder.get('sda_pin', '?')} SDA / {encoder.get('scl_pin', '?')} SCL")
        self._show_offsets(config)
        self._loading = False
        self._dirty = False
        self._status.configure(text="Showing the robot's current mapping.", foreground=theme.MUTED)
        self._refresh_buttons()

    def set_can_apply(self, can_apply: bool, reason: str = "") -> None:
        self._can_apply = can_apply
        self._apply_reason = reason
        self._refresh_buttons()

    def show_result(self, ok: bool, message: str, errors: list[str]) -> None:
        if ok:
            self._dirty = False
            self._status.configure(text=message, foreground=theme.OK)
        else:
            self._status.configure(text="\n".join([message, *errors]), foreground=theme.ERROR)
        self._refresh_buttons()

    def _show_offsets(self, config: dict[str, Any]) -> None:
        for name, v in self._module_vars.items():
            v["offset"].set(str(config["modules"][name]["offset"]))

    def _on_edit(self, *_args: object) -> None:
        if self._loading:
            return
        self._dirty = True
        self._status.configure(text="Unsaved changes.", foreground=theme.WARN)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_config = self._config is not None
        self._revert_button.state(["!disabled"] if self._dirty and has_config else ["disabled"])
        self._apply_button.state(["!disabled"] if self._dirty and has_config and self._can_apply else ["disabled"])
        for widget in self._inputs:
            if isinstance(widget, ttk.Combobox):
                widget.state(["readonly", "!disabled"] if has_config else ["disabled"])
            else:
                widget.state(["!disabled"] if has_config else ["disabled"])
        if self._dirty and has_config and not self._can_apply and self._apply_reason:
            self._status.configure(text=f"Unsaved changes. {self._apply_reason}", foreground=theme.WARN)

    def _collect(self) -> dict[str, Any]:
        modules = {name: {key: var.get() for key, var in v.items() if key != "offset"}
                   for name, v in self._module_vars.items()}
        motors = {motor_id: {"hbridge": v["hbridge"].get(), "channel": v["channel"].get()}
                  for motor_id, v in self._motor_vars.items()}
        encoders = {encoder_id: {"bus": var.get().strip()} for encoder_id, var in self._encoder_vars.items()}
        return {"modules": modules, "motors": motors, "encoders": encoders}

    def _revert(self) -> None:
        if self._config is not None:
            self._dirty = False
            self.load(self._config)

    def _apply(self) -> None:
        if self._config is None:
            return
        update = self._collect()
        try:
            errors = validate_config(merge_config(self._config, update))
        except ConfigError as exc:
            errors = [str(exc)]
        if errors:
            self.show_result(False, "Fix these before applying:", errors)
            return
        if self._apply_callback(update):
            self._status.configure(text="Sent to the robot...", foreground=theme.MUTED)
        else:
            self.show_result(False, "Not connected to the robot.", [])
