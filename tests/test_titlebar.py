import sys
import tkinter as tk

import pytest

from station import theme
from station.titlebar import (CLOSE_HOVER, CaptionButton, CaptionButtons, NativeFrame, TopEdgeGrip, bind_drag,
                              caption_free_rect, top_edge)


@pytest.fixture
def parent(tk_root):
    """A shown (but off-screen) window: Tk only delivers mouse events to shown widgets."""
    window = tk.Toplevel(tk_root)
    window.geometry("+-3000+-3000")
    frame = tk.Frame(window)
    frame.pack()
    yield frame
    window.destroy()


def show(widget):
    widget.update()  # map the newly packed widgets before sending them events


def click(widget, x=5, y=5, release_at=None):
    widget.event_generate("<ButtonPress-1>", x=x, y=y)
    rx, ry = release_at or (x, y)
    widget.event_generate("<ButtonRelease-1>", x=rx, y=ry)


def test_caption_buttons_run_their_commands(parent):
    calls = []
    buttons = CaptionButtons(parent, lambda: calls.append("min"), lambda: calls.append("max"),
                             lambda: calls.append("close"))
    buttons.pack()
    show(buttons)
    for name in ("minimize", "maximize", "close"):
        click(buttons.buttons[name])
    assert calls == ["min", "max", "close"]


def test_releasing_outside_a_caption_button_cancels(parent):
    calls = []
    button = CaptionButton(parent, "close", lambda: calls.append("close"))
    button.pack()
    show(button)
    click(button, release_at=(-20, 5))
    click(button, release_at=(5, CaptionButton.HEIGHT + 3))
    assert calls == []


def test_close_turns_red_on_hover_and_others_stay_dark(parent):
    close = CaptionButton(parent, "close", lambda: None)
    minimize = CaptionButton(parent, "minimize", lambda: None)
    close.pack()
    minimize.pack()
    show(close)
    assert close.background == theme.PAPER
    for button in (close, minimize):
        button.event_generate("<Enter>")
    assert close.background == CLOSE_HOVER and close.foreground == "#FFFFFF"
    assert minimize.background == theme.FAINT and minimize.foreground == theme.INK
    close.event_generate("<Leave>")
    assert close.background == theme.PAPER


def test_maximize_button_shows_restore_while_maximized(parent):
    buttons = CaptionButtons(parent, lambda: None, lambda: None, lambda: None)
    maximize = buttons.buttons["maximize"]
    assert len(maximize.find_withtag("glyph")) == 1  # one square
    buttons.show_maximized(True)
    assert maximize.restore_glyph and len(maximize.find_withtag("glyph")) == 2  # two overlapping squares
    buttons.show_maximized(False)
    assert len(maximize.find_withtag("glyph")) == 1


def test_caption_buttons_scale_with_the_screen(parent):
    button = CaptionButton(parent, "minimize", lambda: None, scale=1.5)
    assert int(button.cget("width")) == 69 and int(button.cget("height")) == 48


def test_dragging_the_header_moves_and_double_click_maximizes(parent):
    calls = []
    label = tk.Label(parent, text="Driver Station")
    label.pack()
    show(label)
    bind_drag([label], lambda: calls.append("move"), lambda: calls.append("toggle"))
    label.event_generate("<ButtonPress-1>", x=3, y=3, time=1000)
    label.event_generate("<ButtonRelease-1>", x=3, y=3, time=1050)
    assert calls == ["move"]
    label.event_generate("<ButtonPress-1>", x=3, y=3, time=1200)  # a second press soon after: a double-click
    assert calls == ["move", "toggle"]


def test_top_edge_grip_resizes_from_the_side_under_the_mouse():
    assert top_edge(2, 1000) == "top-left"
    assert top_edge(500, 1000) == "top"
    assert top_edge(995, 1000) == "top-right"


def test_top_edge_grip_reports_the_edge(parent):
    edges = []
    grip = TopEdgeGrip(parent, edges.append)
    grip.pack(fill="x")
    show(grip)
    grip.event_generate("<ButtonPress-1>", x=1, y=1)
    assert edges == ["top-left"]


def test_caption_space_goes_to_the_app():
    window = (100, 100, 900, 700)
    default = (108, 131, 892, 692)  # what Windows would leave: borders and a 31 px caption
    assert caption_free_rect(window, default, maximized=False) == (108, 100, 892, 692)


def test_maximized_window_keeps_its_top_on_screen():
    # A maximized window hangs 8 px past every screen edge.
    window = (-8, -8, 1928, 1160)
    default = (0, 23, 1920, 1152)
    assert caption_free_rect(window, default, maximized=True) == (0, 0, 1920, 1152)


def test_native_frame_does_nothing_where_it_cannot_work(tk_root, monkeypatch):
    monkeypatch.setattr("station.titlebar.IS_WINDOWS", False)
    frame = NativeFrame(tk_root)
    assert frame.install() is False and not frame.active
    frame.start_move()  # harmless without a hooked window
    frame.reveal()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_native_frame_removes_the_caption_on_windows(tk_root):
    import ctypes
    from ctypes import wintypes

    window = tk.Toplevel(tk_root)
    window.geometry("400x300+-3000+-3000")  # off screen
    try:
        frame = NativeFrame(window)
        assert frame.install()
        frame.reveal()
        window.update()
        user32 = ctypes.windll.user32
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        outer = wintypes.RECT()
        user32.GetWindowRect(frame.hwnd, ctypes.byref(outer))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(frame.hwnd, ctypes.byref(origin))
        assert origin.y == outer.top  # no caption above the app
        assert origin.x > outer.left  # the side borders (for resizing) are still there
        assert window.attributes("-alpha") == 1.0
    finally:
        window.destroy()


_MOVE_LOOP_SCRIPT = r'''
import ctypes, sys, threading, time, tkinter as tk
from ctypes import wintypes
from station.titlebar import NativeFrame
user32 = ctypes.WinDLL("user32")
cursor = wintypes.POINT()
user32.GetCursorPos(ctypes.byref(cursor))
root = tk.Tk()
root.geometry("300x200+-3000+-3000")
frame = NativeFrame(root)
assert frame.install()
frame.reveal()
frame._user32.GetAsyncKeyState = lambda button: -32768  # as if the mouse button was held
ticks = []
def tick():
    ticks.append(1)
    root.after(20, tick)
def end_move_later():
    time.sleep(0.6)
    user32.PostMessageW(frame.hwnd, 0x0100, 0x1B, 0)  # Escape ends the move
def start():  # a Tk event handler, like a click on the title
    threading.Thread(target=end_move_later, daemon=True).start()
    frame._system_command(0xF010)  # SC_MOVE, keyboard flavour: no mouse needed
    root.after(1000, lambda: (print("ticks", len(ticks)), root.destroy()))
tick()
root.after(200, start)
try:
    root.mainloop()
finally:
    user32.SetCursorPos(cursor.x, cursor.y)
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_moving_the_window_keeps_the_app_running():
    """Windows' move loop runs Tk's timers; started the wrong way that aborted the whole app."""
    import subprocess
    from pathlib import Path

    result = subprocess.run([sys.executable, "-c", _MOVE_LOOP_SCRIPT], capture_output=True, text=True, timeout=30,
                            cwd=Path(__file__).resolve().parent.parent)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.split()[-1]) > 20  # the 50 Hz timer kept running
