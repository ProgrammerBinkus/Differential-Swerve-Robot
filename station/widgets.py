"""Reusable widgets: cards, number rows, status lights and the terminal."""

from __future__ import annotations

import datetime
import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from station import theme


class Card(ttk.Frame):
    """A raised panel with an optional heading."""

    def __init__(self, parent: tk.Misc, title: str = "", padding: int = 14) -> None:
        super().__init__(parent, style="Card.TFrame", padding=padding)
        self.columnconfigure(0, weight=1)
        self.body_row = 0
        if title:
            ttk.Label(self, text=title, style="CardHeading.TLabel").grid(row=0, column=0, sticky="w",
                                                                         pady=(0, 8))
            self.body_row = 1


def _decimals(resolution: float) -> int:
    return max(0, -int(math.floor(math.log10(resolution)))) if resolution < 1 else 0


class NumberRow(ttk.Frame):
    """A label, a slider and a text box for typing an exact value.

    The slider and the text box stay in sync. Typed values are applied on
    Enter or when the box loses focus, and are clamped to the allowed range.
    """

    def __init__(self, parent: tk.Misc, label: str, minimum: float, maximum: float, value: float,
                 resolution: float = 0.1, unit: str = "",
                 on_change: Optional[Callable[[float], None]] = None, card: bool = True) -> None:
        super().__init__(parent, style="Card.TFrame" if card else "TFrame")
        self._minimum, self._maximum = minimum, maximum
        self._resolution = resolution
        self._decimals = _decimals(resolution)
        self._on_change = on_change
        self._value = value
        self._updating = False

        label_style = "Card.TLabel" if card else "TLabel"
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, style=label_style, width=22).grid(row=0, column=0, sticky="w")
        self._scale = ttk.Scale(self, from_=minimum, to=maximum, orient="horizontal",
                                command=self._on_slider)
        self._scale.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        self._text = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._text, width=8, justify="right")
        self._entry.grid(row=0, column=2)
        self._entry.bind("<Return>", self._on_entry)
        self._entry.bind("<FocusOut>", self._on_entry)
        muted = "CardMuted.TLabel" if card else "Muted.TLabel"
        ttk.Label(self, text=unit, style=muted, width=6).grid(row=0, column=3, sticky="w", padx=(4, 0))
        self.set(value, notify=False)

    def get(self) -> float:
        return self._value

    def set(self, value: float, notify: bool = True) -> None:
        value = max(self._minimum, min(self._maximum, value))
        value = round(value, max(self._decimals, 3))
        self._value = value
        self._updating = True
        self._scale.set(value)
        self._updating = False
        self._text.set(f"{value:.{self._decimals}f}")
        if notify and self._on_change is not None:
            self._on_change(value)

    def set_enabled(self, enabled: bool) -> None:
        state = "!disabled" if enabled else "disabled"
        self._scale.state([state])
        self._entry.state([state])

    def _on_slider(self, text: str) -> None:
        if self._updating:
            return
        steps = round((float(text) - self._minimum) / self._resolution)
        self.set(self._minimum + steps * self._resolution)

    def _on_entry(self, _event: tk.Event) -> None:
        try:
            typed = float(self._text.get())
        except ValueError:
            self._text.set(f"{self._value:.{self._decimals}f}")  # put back the last good value
            return
        if typed != self._value:
            self.set(typed)  # typed values keep full precision, not the slider step


class StatusLight(ttk.Frame):
    """A colored dot with a label and a detail line."""

    COLORS = {"ok": theme.OK, "warn": theme.WARN, "error": theme.ERROR, "off": theme.BORDER}

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent, style="Card.TFrame", padding=(10, 6))
        self._dot = tk.Canvas(self, width=12, height=12, bg=theme.SURFACE, highlightthickness=0)
        self._dot.grid(row=0, column=0, rowspan=2, padx=(0, 8))
        self._circle = self._dot.create_oval(1, 1, 11, 11, fill=theme.BORDER, outline="")
        ttk.Label(self, text=title, style="CardBold.TLabel").grid(row=0, column=1, sticky="w")
        self._detail = ttk.Label(self, text="", style="Status.TLabel")
        self._detail.grid(row=1, column=1, sticky="w")

    def set(self, state: str, detail: str) -> None:
        self._dot.itemconfigure(self._circle, fill=self.COLORS[state])
        self._detail.configure(text=detail)


class Terminal(ttk.Frame):
    """Scrolling read-only log of what the robot sends."""

    MAX_LINES = 2000
    LEVEL_COLORS = {"DEBUG": theme.MUTED, "INFO": theme.TEXT, "WARNING": theme.WARN,
                    "ERROR": theme.ERROR, "CRITICAL": theme.ERROR}

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._text = tk.Text(self, bg=theme.BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                             font=theme.FONT_MONO, relief="flat", wrap="word", height=8,
                             padx=8, pady=6, highlightthickness=0, state="disabled")
        self._text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.tag_configure("time", foreground=theme.MUTED)
        for source, color in (("robot", theme.ACCENT), ("station", theme.MOTOR), ("data", theme.SENSOR)):
            self._text.tag_configure(f"source-{source}", foreground=color)
        for level, color in self.LEVEL_COLORS.items():
            self._text.tag_configure(level, foreground=color)

    def write(self, source: str, message: str, level: str = "INFO") -> None:
        at_bottom = self._text.yview()[1] >= 0.999
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._text.configure(state="normal")
        self._text.insert("end", f"{stamp} ", "time")
        self._text.insert("end", f"[{source}] ", f"source-{source}")
        self._text.insert("end", message + "\n", level if level in self.LEVEL_COLORS else "INFO")
        lines = int(self._text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self._text.delete("1.0", f"{lines - self.MAX_LINES}.0")
        self._text.configure(state="disabled")
        if at_bottom:
            self._text.see("end")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
