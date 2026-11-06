"""Keyboard driving: the keymap, and which keys are held right now.

Keys are turned into the same stick values a gamepad produces, so they go
through the same deadzone and sensitivity shaping as the controller.

Safety:

* Keys typed into a text box (the robot address, a number box, a bus path)
  never drive the robot.
* When the window loses focus every key counts as released, because Windows
  will not send this window the key-up for a key let go elsewhere.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Optional

# (action, label, keys). Key names are Tk keysyms, lower case.
KEYMAP: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("forward", "Drive forward", ("w", "up")),
    ("back", "Drive back", ("s", "down")),
    ("left", "Strafe left", ("a",)),
    ("right", "Strafe right", ("d",)),
    ("turn_left", "Turn left", ("j", "left")),
    ("turn_right", "Turn right", ("l", "right")),
)
ACTION_OF_KEY = {key: action for action, _label, keys in KEYMAP for key in keys}
KEY_LABELS = {"up": "↑", "down": "↓", "left": "←", "right": "→"}

# Widgets where keys mean typing or choosing, not driving.
_TEXT_INPUT_CLASSES = {"Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox", "Listbox"}


def key_label(key: str) -> str:
    return KEY_LABELS.get(key, key.upper())


def sticks_from_actions(held: set[str]) -> tuple[float, float, float]:
    """Held actions -> (left_x, left_y, right_x), in gamepad convention (+y is stick pulled down).

    Two direction keys together (W+D) give a diagonal of full length, not
    1.41 times full speed.
    """
    x = float(("right" in held) - ("left" in held))
    y = float(("back" in held) - ("forward" in held))
    turn = float(("turn_right" in held) - ("turn_left" in held))
    length = math.hypot(x, y)
    if length > 1.0:
        x, y = x / length, y / length
    return x, y, turn


def is_text_input(widget: object) -> bool:
    if not isinstance(widget, tk.Misc):
        return True  # Tk-internal widgets (a combobox's drop-down list) arrive as plain path strings
    try:
        return widget.winfo_class() in _TEXT_INPUT_CLASSES
    except tk.TclError:
        return True


class KeyboardDrive:
    """Tracks held driving keys for the whole window while keyboard control is on."""

    def __init__(self, root: tk.Tk, on_change: Optional[Callable[[set[str]], None]] = None) -> None:
        self._root = root
        self._on_change = on_change
        self._held: set[str] = set()   # physical keys, so W and ↑ held together release separately
        self._enabled = False
        root.bind_all("<KeyPress>", self._on_press, add="+")
        root.bind_all("<KeyRelease>", self._on_release, add="+")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, on: bool) -> None:
        self._enabled = on
        if not on:
            self.release_all()

    @property
    def held_actions(self) -> set[str]:
        return {ACTION_OF_KEY[key] for key in self._held}

    @property
    def pause_reason(self) -> Optional[str]:
        """Why keys cannot drive right now (``"unfocused"`` or ``"typing"``), or ``None`` if they can."""
        try:
            focus = self._root.focus_get()
        except KeyError:  # Tk cannot name a combobox drop-down that has focus
            return "typing"
        if focus is None:
            return "unfocused"
        return "typing" if is_text_input(focus) else None

    @property
    def paused(self) -> bool:
        return self.pause_reason is not None

    def poll(self) -> Optional[tuple[float, float, float]]:
        """Stick values from the keyboard, or ``None`` while keyboard control is off."""
        if not self._enabled:
            return None
        if self.paused:
            self.release_all()
        return sticks_from_actions(self.held_actions)

    def release_all(self) -> None:
        if self._held:
            self._held.clear()
            self._notify()

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change(self.held_actions)

    def _on_press(self, event: tk.Event) -> None:
        key = str(event.keysym).lower()
        if not self._enabled or key not in ACTION_OF_KEY or is_text_input(event.widget):
            return
        if key not in self._held:  # Windows repeats key-down while a key is held
            self._held.add(key)
            self._notify()

    def _on_release(self, event: tk.Event) -> None:
        key = str(event.keysym).lower()
        if key in self._held:  # wherever focus is now, a released key is released
            self._held.discard(key)
            self._notify()
