"""Reads the Xbox controller with pygame's SDL GameController API.

The GameController API names inputs the same way for every Xbox-style pad
(left stick, right stick, Back/View, Start/Menu), so no per-driver axis
numbers are needed. No pygame window is opened; the Tk window is the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Must be set before pygame initializes SDL: keep reading the pad while the
# Tk window (not a pygame window) has focus.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402
from pygame._sdl2 import controller  # noqa: E402

_AXIS_SCALE = 32767.0


@dataclass
class GamepadState:
    connected: bool = False
    name: str = ""
    left_x: float = 0.0
    left_y: float = 0.0     # +1 is stick pulled down
    right_x: float = 0.0
    back: bool = False      # "-" / View: Swerve Set Zero
    start: bool = False     # "+" / Menu: Return to Zero


class Gamepad:
    """Polls the first connected game controller and handles hot-plugging."""

    RESCAN_INTERVAL_TICKS = 25  # look for a newly plugged-in pad about twice a second

    def __init__(self) -> None:
        pygame.display.init()   # the event queue needs it; no window is created
        pygame.joystick.init()
        controller.init()
        self._pad: controller.Controller | None = None
        self._ticks = 0

    def poll(self) -> GamepadState:
        pygame.event.pump()
        for _ in pygame.event.get():
            pass  # drain the queue; state is read directly below

        if self._pad is not None and not self._pad.attached():
            self._pad = None
        if self._pad is None:
            self._ticks += 1
            if self._ticks % self.RESCAN_INTERVAL_TICKS == 1:
                self._open_first()
        if self._pad is None:
            return GamepadState()

        def axis(which: int) -> float:
            return max(-1.0, min(1.0, self._pad.get_axis(which) / _AXIS_SCALE))

        return GamepadState(
            connected=True,
            name=self._pad.name,
            left_x=axis(pygame.CONTROLLER_AXIS_LEFTX),
            left_y=axis(pygame.CONTROLLER_AXIS_LEFTY),
            right_x=axis(pygame.CONTROLLER_AXIS_RIGHTX),
            back=bool(self._pad.get_button(pygame.CONTROLLER_BUTTON_BACK)),
            start=bool(self._pad.get_button(pygame.CONTROLLER_BUTTON_START)),
        )

    def _open_first(self) -> None:
        for index in range(controller.get_count()):
            if controller.is_controller(index):
                try:
                    self._pad = controller.Controller(index)
                except pygame.error:
                    continue
                return

    def close(self) -> None:
        controller.quit()
        pygame.quit()
