"""Turns raw MT6701 readings into a continuous steering angle."""

from __future__ import annotations

from typing import Optional

from common.config import ENCODER_COUNTS
from robot.constants import ENCODER_TO_MODULE_RATIO, TAU


class SteeringAngleTracker:
    """Unwraps the encoder and converts it to a module angle.

    The encoder is geared 2:1 to the module, so one encoder revolution is only
    180 degrees of steering and a single reading cannot tell a wheel at 10
    degrees from one at 190. The tracker therefore:

    1. On the first reading, assumes the module is within +/-90 degrees of zero
       (the BOM's start-up rule) and picks that solution.
    2. On every later reading, takes the shortest step from the previous one
       and adds it to a running count. This is only correct if the encoder
       moves less than half a turn (90 degrees of steering) between reads,
       which the steer output limit and the 200 Hz loop guarantee.

    The angle is counter-clockwise positive; ``invert`` flips the encoder's
    direction to match.
    """

    def __init__(self, offset: int = 0, invert: bool = False,
                 counts: int = ENCODER_COUNTS, ratio: float = ENCODER_TO_MODULE_RATIO) -> None:
        self._offset = offset % counts
        self._sign = -1 if invert else 1
        self._counts = counts
        self._half = counts // 2
        self._ratio = ratio
        self._last_raw: Optional[int] = None
        self._total = 0  # encoder counts from zero, unwrapped and sign-corrected

    @property
    def initialized(self) -> bool:
        return self._last_raw is not None

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def angle_rad(self) -> float:
        return self._total * TAU / (self._counts * self._ratio)

    def step_to(self, raw: int) -> int:
        """Encoder counts from the last reading to ``raw``, the short way round (before ``invert``)."""
        if self._last_raw is None:
            raise RuntimeError("no earlier reading to step from")
        return (raw - self._last_raw + self._half) % self._counts - self._half

    def update(self, raw: int) -> None:
        if self._last_raw is None:
            relative = (raw - self._offset) % self._counts
            if relative >= self._half:
                relative -= self._counts  # now in [-half, half): within +/-90 degrees of zero
            self._total = self._sign * relative
        else:
            self._total += self._sign * self.step_to(raw)
        self._last_raw = raw

    def zero_here(self) -> int:
        """Make the current position the zero angle. Returns the new offset."""
        if self._last_raw is None:
            raise RuntimeError("cannot zero before the first encoder reading")
        self._offset = self._last_raw
        self._total = 0
        return self._offset
