"""Visual style of the driver station, matching wiring sheet E-01 (dark).

The sheet's look: an engineering drawing. Panels on thin rules (with rounded corners),
condensed uppercase labels, ink-outlined parts, color used only for harness
layers and status, and yellow for whatever is selected.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# Surfaces and ink (the sheet's dark-mode tokens).
PAPER = "#11171B"      # window background
SHEET = "#182026"      # panels and the drawing
FIELD = "#141B20"      # text fields
FAINT = "#26313A"      # hover, dimmed items
RULE = "#33414B"       # borders and dividers
MUTED = "#97A6B0"
INK = "#E4EAEE"
HIGHLIGHT = "#F5C518"  # selection
HIGHLIGHT_INK = "#2A2100"

# Harness layers, as on the wiring sheet.
WIRE_BATTERY = "#FF6B6B"
WIRE_5V = "#FFA94D"
WIRE_3V3 = "#B197FC"
WIRE_CONTROL = "#69DB7C"
WIRE_I2C = "#74C0FC"
WIRE_MOTOR = "#D4A373"

OK = "#69DB7C"
WARN = "#FFB454"
ERROR = "#FF6B6B"

# Fonts are filled in by apply_theme() from what is installed: Bahnschrift
# Condensed stands in for the sheet's Barlow Condensed on Windows.
DISPLAY = "TkDefaultFont"
BODY = "TkDefaultFont"
MONO = "TkFixedFont"
FONT = (BODY, 10)
FONT_SMALL = (BODY, 9)
FONT_BOLD = (BODY, 10, "bold")
FONT_MONO = (MONO, 9)
FONT_LABEL = (DISPLAY, 10)      # uppercase section labels
FONT_HEADING = (DISPLAY, 15)
FONT_TITLE = (DISPLAY, 26)


def _first_installed(*families: str) -> str:
    installed = set(tkfont.families())
    return next((family for family in families if family in installed), "TkDefaultFont")


def display_font(size: int) -> tuple[str, int]:
    return (DISPLAY, size)


CORNER_RADIUS = 6   # px at 96 dpi, for panel outlines
CORNER_INSET = 3    # padding that keeps square content inside the corners; set by apply_theme()
TILE = 64           # px of plain edge/fill in a panel image (see rounded_box_image)
_images: list[tk.PhotoImage] = []   # Tk forgets an image once Python drops it


def corner_inset(radius: int) -> int:
    """How far in a square corner must sit to stay inside a rounded outline of ``radius``."""
    # The square's corner (p, p) must lie inside the outline's inner edge: (r - p) * sqrt(2) <= r - 1.
    return math.ceil(radius - (radius - 1) / math.sqrt(2))


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _blend(weighted: list[tuple[str, int]]) -> str:
    """The average of colors, each counted ``weight`` times."""
    total = sum(weight for _color, weight in weighted)
    channels = [sum(_rgb(color)[i] * weight for color, weight in weighted) / total for i in range(3)]
    return "#" + "".join(f"{round(c):02x}" for c in channels)


def rounded_box_image(root: tk.Misc, radius: int, outline: str, fill: str, outside: str) -> tk.PhotoImage:
    """A small square of a rounded box (1 px outline), anti-aliased against ``outside``.

    A ttk image element keeps the ``radius + 1`` border fixed and tiles the rest to fill the
    widget. Tiling repeats the middle part, so it is made ``TILE`` px wide: a 1 px middle would be
    copied once per pixel of a big panel on every redraw, which freezes the window.
    """
    small = 2 * radius + 3                # just the corners and a 1 px middle, sampled 4 x 4 per pixel
    half = small / 2
    core = half - 0.5 - radius            # the straight part of each side, from the middle
    samples = [(i + 0.5) / 4 for i in range(4)]
    grid = []
    for y in range(small):
        row = []
        for x in range(small):
            weights = {outside: 0, outline: 0, fill: 0}
            for sy in samples:
                for sx in samples:
                    qx = abs(x + sx - half) - core
                    qy = abs(y + sy - half) - core
                    # Signed distance from the outline's center line (negative inside).
                    d = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius
                    weights[outside if d > 0.5 else fill if d < -0.5 else outline] += 1
            row.append(_blend(list(weights.items())))
        grid.append(row)
    # Widen the 1 px middle to TILE px.
    middle = small // 2
    stretch = [i for i in range(small) for _ in range(TILE if i == middle else 1)]
    rows = ["{" + " ".join(grid[y][x] for x in stretch) + "}" for y in stretch]
    size = len(stretch)
    image = tk.PhotoImage(master=root, width=size, height=size)
    image.put(" ".join(rows))
    _images.append(image)
    return image


def rounded_frame_style(style: ttk.Style, name: str, outline: str, fill: str, outside: str, radius: int) -> None:
    """Make ``name`` (a TFrame style) a rounded box.

    A frame doesn't take its padding from the style, so give the frame ``padding=CORNER_INSET``
    (or more) to keep content clear of the corners.
    """
    image = rounded_box_image(style.master, radius, outline, fill, outside)
    element = f"{name}.rounded.{image}"   # elements can't be replaced, so a new one each time
    style.element_create(element, "image", image, border=radius + 1, sticky="nsew")
    style.layout(name, [(element, {"sticky": "nsew"})])
    style.configure(name, background=fill)


def apply_theme(root: tk.Tk) -> None:
    global DISPLAY, BODY, MONO, FONT, FONT_SMALL, FONT_BOLD, FONT_MONO, FONT_LABEL, FONT_HEADING, FONT_TITLE
    DISPLAY = _first_installed("Barlow Condensed SemiBold", "Bahnschrift SemiBold Condensed",
                               "Bahnschrift Condensed", "Segoe UI Semibold")
    BODY = _first_installed("IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI")
    MONO = _first_installed("IBM Plex Mono", "Cascadia Mono", "Consolas")
    FONT, FONT_SMALL, FONT_BOLD = (BODY, 10), (BODY, 9), (BODY, 10, "bold")
    FONT_MONO = (MONO, 9)
    FONT_LABEL, FONT_HEADING, FONT_TITLE = (DISPLAY, 10), (DISPLAY, 15), (DISPLAY, 26)

    root.configure(bg=PAPER)
    # Set the named default fonts rather than "*Font": an option-database font
    # would override every ttk style's font.
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=BODY, size=10)
    root.option_add("*TCombobox*Listbox.background", SHEET)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", HIGHLIGHT)
    root.option_add("*TCombobox*Listbox.selectForeground", HIGHLIGHT_INK)
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.relief", "flat")

    style = ttk.Style(root)
    style.theme_use("clam")
    # Flat everywhere: clam draws bevels with light/dark colors, so match them to the fill.
    style.configure(".", background=PAPER, foreground=INK, fieldbackground=FIELD, bordercolor=RULE,
                    lightcolor=PAPER, darkcolor=PAPER, troughcolor=FIELD, focuscolor=HIGHLIGHT,
                    selectbackground=HIGHLIGHT, selectforeground=HIGHLIGHT_INK, insertcolor=INK,
                    font=FONT, borderwidth=1)

    style.configure("TFrame", background=PAPER)
    # Panels are rounded boxes. Panels whose content runs edge to edge (the drawing, the title
    # block, the joystick readout) are padded by CORNER_INSET so that content clears the corners.
    global CORNER_INSET
    radius = max(2, round(CORNER_RADIUS * root.winfo_fpixels("1i") / 96))
    CORNER_INSET = corner_inset(radius)
    rounded_frame_style(style, "Card.TFrame", RULE, SHEET, PAPER, radius)
    rounded_frame_style(style, "Drawing.TFrame", INK, SHEET, PAPER, radius)
    rounded_frame_style(style, "Readout.TFrame", RULE, FIELD, SHEET, radius)
    style.configure("Plain.TFrame", background=SHEET, borderwidth=0)

    # Labels: <Surface><Role>.TLabel, surface "" = paper, "Card" = sheet.
    for prefix, bg in (("", PAPER), ("Card", SHEET)):
        style.configure(f"{prefix}.TLabel" if prefix else "TLabel", background=bg, foreground=INK)
        style.configure(f"{prefix}Muted.TLabel", background=bg, foreground=MUTED, font=FONT_SMALL)
        style.configure(f"{prefix}Bold.TLabel", background=bg, foreground=INK, font=FONT_BOLD)
        style.configure(f"{prefix}Label.TLabel", background=bg, foreground=MUTED, font=FONT_LABEL)
        style.configure(f"{prefix}Heading.TLabel", background=bg, foreground=INK, font=FONT_HEADING)
        style.configure(f"{prefix}Title.TLabel", background=bg, foreground=INK, font=FONT_TITLE)
        style.configure(f"{prefix}Mono.TLabel", background=bg, foreground=INK, font=FONT_MONO)
    style.configure("Status.TLabel", background=SHEET, foreground=MUTED, font=FONT_SMALL)

    def button(name: str, bg: str, fg: str, hover: str, font=FONT, padding=(14, 6)) -> None:
        border = RULE if bg == SHEET else bg
        style.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg, darkcolor=bg,
                        font=font, padding=padding, focusthickness=0, relief="solid", borderwidth=1)
        style.map(name, background=[("disabled", SHEET), ("pressed", hover), ("active", hover)],
                  lightcolor=[("disabled", SHEET), ("active", hover)], darkcolor=[("disabled", SHEET), ("active", hover)],
                  bordercolor=[("disabled", RULE), ("active", MUTED if bg == SHEET else hover)],
                  foreground=[("disabled", RULE)])

    button("TButton", SHEET, INK, FAINT)
    button("Accent.TButton", HIGHLIGHT, HIGHLIGHT_INK, "#FFD43B")
    button("Enable.TButton", OK, PAPER, "#8CE99A", (DISPLAY, 16), (14, 10))
    button("Disable.TButton", ERROR, PAPER, "#FF8787", (DISPLAY, 16), (14, 10))

    style.configure("TEntry", fieldbackground=FIELD, foreground=INK, bordercolor=RULE, lightcolor=FIELD,
                    darkcolor=FIELD, padding=(6, 4))
    style.map("TEntry", bordercolor=[("focus", HIGHLIGHT)], lightcolor=[("focus", FIELD)],
              fieldbackground=[("disabled", SHEET)], foreground=[("disabled", MUTED)])
    style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=INK, bordercolor=RULE,
                    lightcolor=FIELD, darkcolor=FIELD, arrowcolor=MUTED, padding=(6, 3), arrowsize=12)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", SHEET)],
              background=[("active", FAINT), ("readonly", FIELD)], bordercolor=[("focus", HIGHLIGHT)],
              foreground=[("disabled", MUTED)], arrowcolor=[("disabled", RULE), ("active", INK)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", INK)])

    for name, bg in (("TCheckbutton", PAPER), ("Card.TCheckbutton", SHEET)):
        style.configure(name, background=bg, foreground=INK, indicatorbackground=FIELD,
                        indicatorforeground=HIGHLIGHT_INK, indicatormargin=(0, 0, 8, 0), indicatorsize=14,
                        upperbordercolor=RULE, lowerbordercolor=RULE, focuscolor=bg)
        style.map(name, background=[("active", bg)], foreground=[("disabled", MUTED)],
                  indicatorbackground=[("disabled", SHEET), ("selected", HIGHLIGHT), ("active", FAINT)],
                  upperbordercolor=[("selected", HIGHLIGHT)], lowerbordercolor=[("selected", HIGHLIGHT)])

    # A thin scrollbar without arrow buttons.
    style.layout("Thin.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Thin.Vertical.TScrollbar", troughcolor=PAPER, background=RULE, bordercolor=PAPER,
                    lightcolor=RULE, darkcolor=RULE, gripcount=0, arrowsize=8)
    style.map("Thin.Vertical.TScrollbar", background=[("active", MUTED)])
    style.configure("TSeparator", background=RULE)
