"""Reusable widgets: panels, sliders, tabs, the title block, status lights and the terminal."""

from __future__ import annotations

import datetime
import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from station import theme


class Card(ttk.Frame):
    """A ruled panel with an optional uppercase heading and a divider under it.

    Content goes in rows 1 and up.
    """

    def __init__(self, parent: tk.Misc, title: str = "", padding: int | tuple = 14) -> None:
        super().__init__(parent, style="Card.TFrame", padding=padding)
        self.columnconfigure(0, weight=1)
        if title:
            head = ttk.Frame(self, style="Plain.TFrame")
            head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            ttk.Label(head, text=title.upper(), style="CardLabel.TLabel").pack(anchor="w")
            tk.Frame(head, height=1, bg=theme.RULE).pack(fill="x", pady=(4, 0))


class Slider(tk.Canvas):
    """A thin track with a round knob. Click or drag to set; ``command`` receives the raw value."""

    HEIGHT = 22
    KNOB_RADIUS = 6

    def __init__(self, parent: tk.Misc, minimum: float, maximum: float,
                 command: Callable[[float], None], background: str = theme.SHEET) -> None:
        super().__init__(parent, height=self.HEIGHT, width=150, bg=background, highlightthickness=0,
                         cursor="hand2")
        self._minimum, self._maximum = minimum, maximum
        self._command = command
        self._value = minimum
        self._enabled = True
        self._hot = False
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._on_pointer)
        self.bind("<B1-Motion>", self._on_pointer)
        self.bind("<Enter>", lambda _e: self._set_hot(True))
        self.bind("<Leave>", lambda _e: self._set_hot(False))

    def set(self, value: float) -> None:
        self._value = value
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw()

    def _span(self) -> tuple[float, float]:
        pad = self.KNOB_RADIUS + 2
        return pad, max(pad + 1, self.winfo_width() - pad)

    def _set_hot(self, hot: bool) -> None:
        self._hot = hot and self._enabled
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        left, right = self._span()
        fraction = (self._value - self._minimum) / ((self._maximum - self._minimum) or 1.0)
        x = left + max(0.0, min(1.0, fraction)) * (right - left)
        y = self.HEIGHT / 2
        ink = theme.INK if self._enabled else theme.RULE
        self.create_line(left, y, right, y, fill=theme.RULE, width=3, capstyle="round")
        self.create_line(left, y, x, y, fill=ink, width=3, capstyle="round")
        r = self.KNOB_RADIUS
        self.create_oval(x - r, y - r, x + r, y + r, fill=theme.HIGHLIGHT if self._hot else theme.SHEET,
                         outline=ink, width=2)

    def _on_pointer(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        left, right = self._span()
        fraction = max(0.0, min(1.0, (event.x - left) / (right - left)))
        self._command(self._minimum + fraction * (self._maximum - self._minimum))


def _decimals(resolution: float) -> int:
    return max(0, -int(math.floor(math.log10(resolution)))) if resolution < 1 else 0


class NumberRow(ttk.Frame):
    """A label, a slider and a box for typing an exact value.

    The slider snaps to ``resolution``; typed values keep full precision. Both
    are clamped to the allowed range and applied on Enter or when the box
    loses focus.
    """

    def __init__(self, parent: tk.Misc, label: str, minimum: float, maximum: float, value: float,
                 resolution: float = 0.1, unit: str = "",
                 on_change: Optional[Callable[[float], None]] = None, label_width: int = 22,
                 unit_width: int = 6) -> None:
        super().__init__(parent, style="Plain.TFrame")
        self._minimum, self._maximum = minimum, maximum
        self._resolution = resolution
        self._decimals = _decimals(resolution)
        self._on_change = on_change
        self._value = value

        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, style="Card.TLabel", width=label_width).grid(row=0, column=0, sticky="w")
        self._slider = Slider(self, minimum, maximum, self._on_slider)
        self._slider.grid(row=0, column=1, sticky="ew", padx=(8, 10))
        self._text = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._text, width=8, justify="right", font=theme.FONT_MONO)
        self._entry.grid(row=0, column=2)
        self._entry.bind("<Return>", self._on_entry)
        self._entry.bind("<FocusOut>", self._on_entry)
        ttk.Label(self, text=unit, style="CardMuted.TLabel", width=unit_width).grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.set(value, notify=False)

    def get(self) -> float:
        return self._value

    def set(self, value: float, notify: bool = True) -> None:
        value = round(max(self._minimum, min(self._maximum, value)), max(self._decimals, 3))
        self._value = value
        self._slider.set(value)
        self._text.set(f"{value:.{self._decimals}f}")
        if notify and self._on_change is not None:
            self._on_change(value)

    def set_enabled(self, enabled: bool) -> None:
        self._slider.set_enabled(enabled)
        self._entry.state(["!disabled" if enabled else "disabled"])

    def _on_slider(self, raw: float) -> None:
        steps = round((raw - self._minimum) / self._resolution)
        value = self._minimum + steps * self._resolution
        if value != self._value:
            self.set(value)

    def _on_entry(self, _event: tk.Event) -> None:
        try:
            typed = float(self._text.get())
        except ValueError:
            self._text.set(f"{self._value:.{self._decimals}f}")  # put back the last good value
            return
        if typed != self._value:
            self.set(typed)


class TabBar(tk.Frame):
    """Uppercase text tabs with a highlight bar under the selected one."""

    def __init__(self, parent: tk.Misc, on_select: Callable[[str], None]) -> None:
        super().__init__(parent, bg=theme.PAPER)
        self._on_select = on_select
        self._tabs: dict[str, tuple[tk.Label, tk.Frame]] = {}
        self._selected: Optional[str] = None

    def add(self, key: str, text: str) -> None:
        cell = tk.Frame(self, bg=theme.PAPER)
        cell.pack(side="left", padx=(0, 26))
        label = tk.Label(cell, text=text.upper(), bg=theme.PAPER, fg=theme.MUTED, font=theme.display_font(14),
                         cursor="hand2", padx=0, pady=4)
        label.pack()
        bar = tk.Frame(cell, height=3, bg=theme.PAPER)
        bar.pack(fill="x")
        label.bind("<Button-1>", lambda _e: self._on_select(key))
        label.bind("<Enter>", lambda _e: label.configure(fg=theme.INK))
        label.bind("<Leave>", lambda _e: label.configure(fg=theme.INK if key == self._selected else theme.MUTED))
        self._tabs[key] = (label, bar)

    def select(self, key: str) -> None:
        self._selected = key
        for name, (label, bar) in self._tabs.items():
            label.configure(fg=theme.INK if name == key else theme.MUTED)
            bar.configure(bg=theme.HIGHLIGHT if name == key else theme.PAPER)


class TitleBlock(tk.Frame):
    """A drawing title block: ruled cells, each with an uppercase key above its value."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=theme.INK, padx=1, pady=1)  # the outer ink frame
        self._inner = tk.Frame(self, bg=theme.RULE)
        self._inner.pack(fill="both", expand=True)
        self._column = 0

    def add_cell(self, key: str) -> tk.Frame:
        """Add a cell and return the frame its value widgets go in."""
        cell = tk.Frame(self._inner, bg=theme.SHEET, padx=12, pady=6)
        cell.grid(row=0, column=self._column, sticky="nsew", padx=(0 if self._column == 0 else 1, 0))
        tk.Label(cell, text=key.upper(), bg=theme.SHEET, fg=theme.MUTED, font=theme.FONT_LABEL).pack(anchor="w")
        value = tk.Frame(cell, bg=theme.SHEET)
        value.pack(anchor="w", fill="x")
        self._column += 1
        return value


class StatusLight(tk.Frame):
    """A colored dot followed by a status text."""

    COLORS = {"ok": theme.OK, "warn": theme.WARN, "error": theme.ERROR, "off": theme.RULE}

    def __init__(self, parent: tk.Misc, background: str = theme.SHEET) -> None:
        super().__init__(parent, bg=background)
        self._dot = tk.Canvas(self, width=10, height=10, bg=background, highlightthickness=0)
        self._dot.pack(side="left", padx=(0, 7))
        self._circle = self._dot.create_oval(1, 1, 9, 9, fill=theme.RULE, outline="")
        self._text = tk.Label(self, text="", bg=background, fg=theme.INK, font=theme.FONT, anchor="w")
        self._text.pack(side="left")

    def set(self, state: str, text: str) -> None:
        self._dot.itemconfigure(self._circle, fill=self.COLORS[state])
        self._text.configure(text=text)


class Terminal(ttk.Frame):
    """Scrolling read-only log of what the robot sends."""

    MAX_LINES = 2000
    LEVEL_COLORS = {"DEBUG": theme.MUTED, "INFO": theme.INK, "WARNING": theme.WARN,
                    "ERROR": theme.ERROR, "CRITICAL": theme.ERROR}
    SOURCE_COLORS = {"robot": theme.WIRE_I2C, "station": theme.WIRE_MOTOR, "data": theme.WIRE_3V3}

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="Plain.TFrame")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._text = tk.Text(self, bg=theme.FIELD, fg=theme.INK, insertbackground=theme.INK, font=theme.FONT_MONO,
                             relief="flat", wrap="word", width=44, height=6, padx=10, pady=8, highlightthickness=1,
                             highlightbackground=theme.RULE, highlightcolor=theme.RULE, state="disabled",
                             spacing1=1, spacing3=1)
        self._text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview, style="Thin.Vertical.TScrollbar")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.tag_configure("time", foreground=theme.RULE)
        for source, color in self.SOURCE_COLORS.items():
            self._text.tag_configure(f"source-{source}", foreground=color)
        for level, color in self.LEVEL_COLORS.items():
            self._text.tag_configure(level, foreground=color)

    def write(self, source: str, message: str, level: str = "INFO") -> None:
        at_bottom = self._text.yview()[1] >= 0.999
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._text.configure(state="normal")
        self._text.insert("end", f"{stamp}  ", "time")
        self._text.insert("end", f"{source.upper():<8}", f"source-{source}")
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
