"""Differential mixing, steer-first desaturation and command rate limiting."""

from __future__ import annotations

from typing import Iterable


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def mix(drive: float, steer: float) -> tuple[float, float]:
    """Motor commands for one module.

    Both motors turning together roll the wheel; turning in opposite
    directions steers it. Solving drive = (a + b) / 2 and steer = (a - b) / 2
    for the two motors gives a = drive + steer and b = drive - steer.
    """
    return drive + steer, drive - steer


def steer_first_scale(plans: Iterable[tuple[float, float]]) -> float:
    """Common factor (0 to 1) for every module's drive so that |drive| + |steer| <= 1.

    Both motors carry drive and steer, so they share one budget. Steering is
    never reduced, because a wheel pointing the wrong way is worse than a
    slower one. The same factor applies to all four modules so the robot keeps
    moving in the commanded direction, only slower.
    """
    scale = 1.0
    for drive, steer in plans:
        room = max(0.0, 1.0 - abs(steer))
        if abs(drive) > room:
            scale = min(scale, room / abs(drive))
    return scale


class RateLimiter:
    """Limits how fast a value may change, in units per second."""

    def __init__(self, rate_per_s: float, value: float = 0.0) -> None:
        self.rate_per_s = rate_per_s
        self.value = value

    def calculate(self, target: float, dt: float) -> float:
        step = self.rate_per_s * dt
        self.value += clamp(target - self.value, step)
        return self.value

    def reset(self, value: float = 0.0) -> None:
        self.value = value
