"""The rounded panel outlines."""

from tkinter import ttk

from station import theme


def _pixel(image, x, y):
    return "#%02x%02x%02x" % tuple(image.get(x, y))


def test_rounded_box_has_outline_edges_fill_inside_and_open_corners(tk_root):
    image = theme.rounded_box_image(tk_root, 6, "#ffffff", "#000080", "#000000")
    size = image.width()
    assert size == image.height() == 2 * 7 + theme.TILE   # fixed 7 px borders, a wide middle to tile
    middle = size // 2
    assert _pixel(image, 0, 0) == "#000000"               # corner: background shows through
    assert _pixel(image, middle, 0) == "#ffffff"          # straight edges: the outline
    assert _pixel(image, 0, middle) == "#ffffff"
    assert _pixel(image, middle, middle) == "#000080"     # inside: the fill
    # On the curve the outline is blended with what is next to it (anti-aliased).
    assert _pixel(image, 1, 2) not in ("#000000", "#ffffff", "#000080")


def test_rounded_frame_style_draws_the_image(tk_root):
    style = ttk.Style(tk_root)
    for _ in range(2):                    # restyling (the theme applied again) must work too
        theme.rounded_frame_style(style, "TestRounded.TFrame", theme.RULE, theme.SHEET, theme.PAPER, 6)
    assert style.layout("TestRounded.TFrame")[0][0].startswith("TestRounded.TFrame.rounded.")
    assert style.lookup("TestRounded.TFrame", "background") == theme.SHEET


def test_corner_inset_keeps_a_square_corner_inside_the_outline():
    for radius in range(2, 16):
        inset = theme.corner_inset(radius)
        # The content's corner pixel sits inside the outline's inner edge, and no further in than needed.
        assert (radius - inset) * 2 ** 0.5 <= radius - 1
        assert (radius - (inset - 1)) * 2 ** 0.5 > radius - 1
    assert theme.corner_inset(6) == 3
