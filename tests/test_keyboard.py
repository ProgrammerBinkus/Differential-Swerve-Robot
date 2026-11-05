"""Keyboard driving: keymap math and the safety rules (typing, focus loss, key repeat)."""

import math
import tkinter as tk
from types import SimpleNamespace

import pytest

from station.keyboard import KeyboardDrive, sticks_from_actions
from station.shaping import shape_inputs

FULL = dict(drive_deadzone_pct=8, drive_sensitivity_pct=100, turn_deadzone_pct=8, turn_sensitivity_pct=100)


def test_w_drives_forward_and_a_strafes_left():
    assert shape_inputs(*sticks_from_actions({"forward"}), **FULL) == pytest.approx((1.0, 0.0, 0.0))
    assert shape_inputs(*sticks_from_actions({"left"}), **FULL) == pytest.approx((0.0, 1.0, 0.0))


def test_j_turns_counter_clockwise_and_l_clockwise():
    assert shape_inputs(*sticks_from_actions({"turn_left"}), **FULL)[2] == pytest.approx(1.0)
    assert shape_inputs(*sticks_from_actions({"turn_right"}), **FULL)[2] == pytest.approx(-1.0)


def test_diagonal_is_full_length_not_longer():
    x, y, _ = sticks_from_actions({"forward", "right"})
    assert math.hypot(x, y) == pytest.approx(1.0)


def test_opposite_keys_cancel():
    assert sticks_from_actions({"forward", "back", "turn_left", "turn_right"}) == (0.0, 0.0, 0.0)


@pytest.fixture(scope="module")
def root():
    # One window for the module: creating many Tk instances in a row is flaky on Windows.
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    window.withdraw()
    yield window
    window.destroy()


def key(widget, keysym):
    return SimpleNamespace(widget=widget, keysym=keysym)


def test_keys_ignored_while_off(root):
    keyboard = KeyboardDrive(root)
    keyboard._on_press(key(root, "w"))
    assert keyboard.poll() is None
    assert keyboard.held_actions == set()


def test_typing_in_a_text_box_does_not_drive(root):
    keyboard = KeyboardDrive(root)
    keyboard.enabled = True
    entry = tk.Entry(root)
    keyboard._on_press(key(entry, "w"))
    keyboard._on_press(key(entry, "Left"))
    assert keyboard.held_actions == set()


def test_held_keys_release_individually(root):
    keyboard = KeyboardDrive(root)
    keyboard.enabled = True
    keyboard._on_press(key(root, "w"))
    keyboard._on_press(key(root, "Up"))
    keyboard._on_press(key(root, "W"))          # auto-repeat with Shift held: still one key
    keyboard._on_release(key(root, "w"))
    assert keyboard.held_actions == {"forward"}  # the arrow is still down
    keyboard._on_release(key(root, "Up"))
    assert keyboard.held_actions == set()


def test_losing_focus_releases_everything(root, monkeypatch):
    keyboard = KeyboardDrive(root)
    keyboard.enabled = True
    keyboard._on_press(key(root, "d"))
    monkeypatch.setattr(root, "focus_get", lambda: None)   # the window is no longer focused
    assert keyboard.poll() == (0.0, 0.0, 0.0)
    assert keyboard.held_actions == set()


def test_turning_keyboard_off_releases_keys(root):
    seen = []
    keyboard = KeyboardDrive(root, on_change=seen.append)
    keyboard.enabled = True
    keyboard._on_press(key(root, "l"))
    keyboard.enabled = False
    assert keyboard.held_actions == set()
    assert seen[-1] == set()
