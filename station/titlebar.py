"""The app's own title bar: the header doubles as the caption, with themed window buttons.

How the native title bar goes away (Windows only):

The window stays an ordinary Windows window with its normal styles, so the
taskbar button, minimize/restore from the taskbar, Aero snap, Win+arrow keys
and maximizing to the work area (not over the taskbar) all keep working. Only
the caption strip is removed: :class:`NativeFrame` hooks the window's
``WM_NCCALCSIZE`` message and gives the caption's space to the app. The left,
right and bottom frame borders stay; on Windows 10/11 they are invisible but
still resize the window. The top edge has no frame left, so a thin strip along
the top of the app resizes it instead. Dragging the header asks Windows to run
its own move loop (``SC_MOVE``), which is what gives snapping for free.

Removing the frame with ``overrideredirect`` instead would lose the taskbar
button, minimizing, snapping and edge resizing, which would all have to be
rebuilt by hand.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Iterable, Optional

from station import theme
from station.windows import IS_WINDOWS

log = logging.getLogger(__name__)

CLOSE_HOVER = "#C42B1C"      # the Windows close-button red
CLOSE_PRESSED = "#B0281A"
EDGE_GRIP_PX = 5             # height of the top resize strip
CORNER_GRIP_PX = 16          # width of its diagonal-resize ends

_WM_NCCALCSIZE = 0x0083
_WM_SYSCOMMAND = 0x0112
_SC_SIZE = 0xF000
_SC_MOVE_MOUSE = 0xF012      # SC_MOVE | HTCAPTION: move with the mouse, as if the caption was dragged
_WMSZ = {"top": 3, "top-left": 4, "top-right": 5}
_SWP_FRAMECHANGED_ONLY = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED
_SUBCLASS_ID = 0x5357  # any number unique to this hook
_WM_START_SYSTEM_COMMAND = 0x8000 + 0x53  # WM_APP + a number of our own
_VK_LBUTTON, _VK_RBUTTON, _SM_SWAPBUTTON = 0x01, 0x02, 23
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000


def caption_free_rect(original: tuple[int, int, int, int], default: tuple[int, int, int, int],
                      maximized: bool) -> tuple[int, int, int, int]:
    """The client area (left, top, right, bottom) once the caption is removed.

    ``original`` is the proposed window rectangle and ``default`` what Windows
    would make the client area. The sides and bottom keep Windows' borders;
    the top keeps none, except when maximized: then the window hangs over the
    screen edge by its border width, so the top is moved in by the same amount
    as the bottom to keep the app fully on screen.
    """
    left, top, right, bottom = default
    if maximized:
        top = original[1] + (original[3] - bottom)
    else:
        top = original[1]
    return left, top, right, bottom


def top_edge(x: int, width: int, corner: int = CORNER_GRIP_PX) -> str:
    """Which edge the top resize strip resizes at ``x``: "top-left", "top" or "top-right"."""
    if x < corner:
        return "top-left"
    if x >= width - corner:
        return "top-right"
    return "top"


_EDGE_CURSORS = {"top": "size_ns", "top-left": "size_nw_se", "top-right": "size_ne_sw"}


class NativeFrame:
    """Hides the Windows caption of ``root`` and lets the app move and resize the window.

    :meth:`install` returns False (and changes nothing) where this is not
    possible, such as on other platforms; the native title bar then stays.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.hwnd: Optional[int] = None
        self._callback = None  # the ctypes hook must stay alive as long as the window

    @property
    def active(self) -> bool:
        return self.hwnd is not None

    def install(self) -> bool:
        """Hide the caption. Call before building the UI, then :meth:`reveal` once it is built.

        Tk only creates the real window when it is first shown (and replaces
        the one it had before), so the window is shown fully transparent here
        to hook it without the old title bar flashing up.
        """
        if not IS_WINDOWS:
            return False
        try:
            self.root.attributes("-alpha", 0.0)
            self.root.update()
            self._install()
        except (AttributeError, OSError, ValueError, tk.TclError):
            log.exception("Could not replace the title bar; keeping the Windows one")
            self.hwnd = None
            return False
        return True

    def reveal(self) -> None:
        """Make the window visible again after :meth:`install`."""
        if not IS_WINDOWS:
            return
        try:
            self.root.attributes("-alpha", 1.0)
            if self.hwnd is not None:
                # Tk leaves the window "layered" after a transparency change, which only slows drawing.
                styles = self._user32.GetWindowLongW(self.hwnd, _GWL_EXSTYLE)
                self._user32.SetWindowLongW(self.hwnd, _GWL_EXSTYLE, styles & ~_WS_EX_LAYERED)
                self._user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, _SWP_FRAMECHANGED_ONLY)
        except (OSError, tk.TclError):
            log.exception("Could not show the window normally")

    def _install(self) -> None:
        import ctypes
        from ctypes import wintypes

        lresult = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       ctypes.c_size_t, ctypes.c_size_t)
        comctl32 = ctypes.WinDLL("comctl32")
        comctl32.SetWindowSubclass.argtypes = (wintypes.HWND, proc_type, ctypes.c_size_t, ctypes.c_size_t)
        comctl32.SetWindowSubclass.restype = wintypes.BOOL
        comctl32.DefSubclassProc.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        comctl32.DefSubclassProc.restype = lresult
        user32 = ctypes.WinDLL("user32")
        user32.IsZoomed.argtypes = (wintypes.HWND,)
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.UINT)
        user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        self._user32 = user32

        # The outer (wrapper) window Tk puts the app in; Tk creates it if it doesn't exist yet.
        hwnd = int(self.root.wm_frame(), 16)
        if not hwnd:
            raise ValueError("no window handle")

        def hook(window, message, wparam, lparam, _subclass_id, _data):
            if message == _WM_START_SYSTEM_COMMAND:
                # Only while the button is still down: a move/size loop started after the
                # release would leave the window stuck to the mouse.
                button = _VK_RBUTTON if user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON
                if not user32.GetAsyncKeyState(button) & 0x8000:
                    return 0
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                user32.ReleaseCapture()  # Tk holds the mouse while a button is down; Windows needs it
                return comctl32.DefSubclassProc(window, _WM_SYSCOMMAND, wparam,
                                                ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF))
            if message == _WM_NCCALCSIZE and wparam:
                rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
                original = (rect.left, rect.top, rect.right, rect.bottom)
                result = comctl32.DefSubclassProc(window, message, wparam, lparam)
                default = (rect.left, rect.top, rect.right, rect.bottom)
                rect.left, rect.top, rect.right, rect.bottom = caption_free_rect(
                    original, default, bool(user32.IsZoomed(window)))
                return result
            return comctl32.DefSubclassProc(window, message, wparam, lparam)

        callback = proc_type(hook)
        if not comctl32.SetWindowSubclass(hwnd, callback, _SUBCLASS_ID, 0):
            raise OSError("SetWindowSubclass failed")
        self._callback = callback
        self.hwnd = hwnd
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FRAMECHANGED_ONLY)  # apply the new frame now

    def _system_command(self, command: int) -> None:
        # Posted, not sent: Windows' move/size loop runs until the mouse is released and
        # keeps Tk's timers running meanwhile. Started from inside a Tk event handler
        # those timers would call back into Python at a moment tkinter can't take it
        # (the app aborts), so the hook starts it from Tk's own event loop instead.
        self._user32.PostMessageW(self.hwnd, _WM_START_SYSTEM_COMMAND, command, 0)

    def start_move(self) -> None:
        """Let Windows move the window with the mouse, until the button is released."""
        if self.active:
            self._system_command(_SC_MOVE_MOUSE)

    def start_resize(self, edge: str) -> None:
        """Let Windows resize the window from ``edge`` ("top", "top-left" or "top-right")."""
        if self.active:
            self._system_command(_SC_SIZE + _WMSZ[edge])

    @property
    def maximized(self) -> bool:
        return self.root.wm_state() == "zoomed"

    def minimize(self) -> None:
        self.root.iconify()

    def toggle_maximize(self) -> None:
        self.root.wm_state("normal" if self.maximized else "zoomed")


def bind_drag(widgets: Iterable[tk.Misc], on_press: Callable[[], None], on_double: Callable[[], None]) -> None:
    """Pressing on ``widgets`` moves the window; double-clicking them maximizes or restores it."""
    for widget in widgets:
        widget.bind("<ButtonPress-1>", lambda _event: on_press(), add="+")
        widget.bind("<Double-Button-1>", lambda _event: on_double(), add="+")


class TopEdgeGrip(tk.Frame):
    """A thin strip along the top of the window that resizes it (the top has no Windows frame)."""

    def __init__(self, parent: tk.Misc, on_resize: Callable[[str], None]) -> None:
        super().__init__(parent, bg=theme.PAPER, height=EDGE_GRIP_PX, cursor=_EDGE_CURSORS["top"])
        self._on_resize = on_resize
        self.bind("<Motion>", lambda event: self.configure(cursor=_EDGE_CURSORS[self._edge(event.x)]))
        self.bind("<ButtonPress-1>", lambda event: self._on_resize(self._edge(event.x)))

    def _edge(self, x: int) -> str:
        return top_edge(x, self.winfo_width())

    def show(self, visible: bool) -> None:
        if visible:
            self.place(x=0, y=0, relwidth=1, height=EDGE_GRIP_PX)
            self.lift()
        else:
            self.place_forget()


class CaptionButton(tk.Canvas):
    """One window button (minimize, maximize/restore or close) with a drawn glyph.

    Like Windows' own, it acts when the mouse is released over it, so pressing
    and sliding off cancels.
    """

    WIDTH, HEIGHT = 46, 32

    def __init__(self, parent: tk.Misc, kind: str, command: Callable[[], None], scale: float = 1.0) -> None:
        self.kind = kind
        self._command = command
        self._scale = scale
        self._width = round(self.WIDTH * scale)
        self._height = round(self.HEIGHT * scale)
        super().__init__(parent, width=self._width, height=self._height, bg=theme.PAPER, highlightthickness=0,
                         borderwidth=0)
        self._hover = False
        self._pressed = False
        self.restore_glyph = False  # maximize button: show "restore" while the window is maximized
        self.bind("<Enter>", lambda _event: self._set(hover=True))
        self.bind("<Leave>", lambda _event: self._set(hover=False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.draw()

    @property
    def background(self) -> str:
        if self.kind == "close":
            if self._pressed:
                return CLOSE_PRESSED
            return CLOSE_HOVER if self._hover else theme.PAPER
        if self._pressed:
            return theme.RULE
        return theme.FAINT if self._hover else theme.PAPER

    @property
    def foreground(self) -> str:
        if self.kind == "close" and (self._hover or self._pressed):
            return "#FFFFFF"
        return theme.INK

    def _set(self, hover: Optional[bool] = None, pressed: Optional[bool] = None) -> None:
        if hover is not None:
            self._hover = hover
        if pressed is not None:
            self._pressed = pressed
        self.draw()

    def _press(self, _event: tk.Event) -> str:
        self._set(pressed=True)
        return "break"  # not a drag, and the window-wide click handler has nothing to do here

    def _release(self, event: tk.Event) -> str:
        inside = 0 <= event.x < self._width and 0 <= event.y < self._height
        self._set(pressed=False, hover=inside)
        if inside:
            self._command()
        return "break"

    def draw(self) -> None:
        self.configure(bg=self.background)
        self.delete("glyph")
        s = self._scale
        size = round(10 * s)
        cx, cy = self._width // 2, self._height // 2
        x0, y0 = cx - size // 2, cy - size // 2
        x1, y1 = x0 + size, y0 + size
        line = max(1, round(s))
        color = self.foreground
        if self.kind == "minimize":
            self.create_line(x0, cy, x1, cy, fill=color, width=line, tags="glyph")
        elif self.kind == "maximize" and not self.restore_glyph:
            self.create_rectangle(x0, y0, x1, y1, outline=color, width=line, tags="glyph")
        elif self.kind == "maximize":
            offset = round(2 * s)
            self.create_line(x0 + offset, y0, x1, y0, x1, y1 - offset, fill=color, width=line, tags="glyph")
            self.create_rectangle(x0, y0 + offset, x1 - offset, y1, outline=color, width=line, tags="glyph")
        else:
            self.create_line(x0, y0, x1 + 1, y1 + 1, fill=color, width=line, tags="glyph")
            self.create_line(x0, y1, x1 + 1, y0 - 1, fill=color, width=line, tags="glyph")


class CaptionButtons(tk.Frame):
    """Minimize, maximize/restore and close, in Windows' order."""

    def __init__(self, parent: tk.Misc, minimize: Callable[[], None], toggle_maximize: Callable[[], None],
                 close: Callable[[], None], scale: float = 1.0) -> None:
        super().__init__(parent, bg=theme.PAPER)
        self.buttons = {
            "minimize": CaptionButton(self, "minimize", minimize, scale),
            "maximize": CaptionButton(self, "maximize", toggle_maximize, scale),
            "close": CaptionButton(self, "close", close, scale),
        }
        for button in self.buttons.values():
            button.pack(side="left")

    def show_maximized(self, maximized: bool) -> None:
        button = self.buttons["maximize"]
        if button.restore_glyph != maximized:
            button.restore_glyph = maximized
            button.draw()
