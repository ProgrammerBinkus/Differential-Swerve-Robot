"""Dark theme for the driver station (colors, fonts and ttk styles)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#0f1419"
SURFACE = "#161d24"
SURFACE_2 = "#1e2731"
BORDER = "#2b3743"
TEXT = "#e4eaee"
MUTED = "#8b99a5"
ACCENT = "#4aa3ff"
OK = "#3fb950"
WARN = "#d29922"
ERROR = "#f85149"
HIGHLIGHT = "#f5c518"

# Part colors, matching the harness colors of the wiring diagram.
POWER = "#ff6b6b"
LOGIC = "#b197fc"
CONTROL = "#69db7c"
SENSOR = "#74c0fc"
MOTOR = "#d4a373"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_HEADING = ("Segoe UI Semibold", 12)
FONT_TITLE = ("Segoe UI Semibold", 15)
FONT_MONO = ("Cascadia Mono", 9)


def apply_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    root.option_add("*Font", FONT)
    # Combobox drop-down lists are plain Tk listboxes.
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", BG)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE_2,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    troughcolor=SURFACE_2, focuscolor=ACCENT, font=FONT,
                    selectbackground=ACCENT, selectforeground=BG, insertcolor=TEXT)

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, relief="flat")
    style.configure("TLabel", background=BG, foreground=TEXT)
    for name, fg, font in (("Muted", MUTED, FONT_SMALL), ("Heading", TEXT, FONT_HEADING),
                           ("Title", TEXT, FONT_TITLE), ("Bold", TEXT, FONT_BOLD)):
        style.configure(f"{name}.TLabel", background=BG, foreground=fg, font=font)
        style.configure(f"Card{name}.TLabel", background=SURFACE, foreground=fg, font=font)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Status.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SMALL)

    style.configure("TButton", background=SURFACE_2, foreground=TEXT, padding=(12, 6),
                    borderwidth=1, focusthickness=0)
    style.map("TButton", background=[("disabled", SURFACE), ("pressed", BORDER), ("active", BORDER)],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=FONT_BOLD)
    style.map("Accent.TButton", background=[("disabled", SURFACE_2), ("active", "#6cb6ff")],
              foreground=[("disabled", MUTED)])
    style.configure("Enable.TButton", background=OK, foreground=BG, font=FONT_HEADING, padding=(12, 10))
    style.map("Enable.TButton", background=[("disabled", SURFACE_2), ("active", "#56d364")],
              foreground=[("disabled", MUTED)])
    style.configure("Disable.TButton", background=ERROR, foreground=BG, font=FONT_HEADING, padding=(12, 10))
    style.map("Disable.TButton", background=[("active", "#ff7b72")])

    style.configure("TEntry", fieldbackground=SURFACE_2, foreground=TEXT, padding=4)
    style.map("TEntry", fieldbackground=[("disabled", SURFACE)], foreground=[("disabled", MUTED)],
              bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT,
                    arrowcolor=TEXT, padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
              foreground=[("disabled", MUTED)], selectbackground=[("readonly", SURFACE_2)],
              selectforeground=[("readonly", TEXT)])

    for parent in ("TCheckbutton", "Card.TCheckbutton"):
        bg = SURFACE if parent.startswith("Card") else BG
        style.configure(parent, background=bg, foreground=TEXT, indicatorbackground=SURFACE_2,
                        indicatorforeground=ACCENT, indicatormargin=4)
        style.map(parent, background=[("active", bg)], foreground=[("disabled", MUTED)],
                  indicatorbackground=[("selected", ACCENT), ("disabled", SURFACE)])

    style.configure("Horizontal.TScale", background=ACCENT, troughcolor=SURFACE_2,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, gripcount=0)
    style.configure("Card.Horizontal.TScale", background=ACCENT, troughcolor=SURFACE_2)

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(18, 8), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE_2)], foreground=[("selected", TEXT)],
              lightcolor=[("selected", ACCENT)])

    style.configure("Vertical.TScrollbar", background=SURFACE_2, troughcolor=BG, arrowcolor=MUTED,
                    bordercolor=BG)
    style.configure("TSeparator", background=BORDER)
