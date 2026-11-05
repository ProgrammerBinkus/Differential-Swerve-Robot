"""Turns raw stick positions into drive commands (deadzone and sensitivity)."""

from __future__ import annotations

import math


def apply_deadband(value: float, deadzone: float) -> float:
    """Zero inside ``deadzone``; rescaled so the output still reaches 1 at full travel."""
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    return math.copysign(min(1.0, (magnitude - deadzone) / (1.0 - deadzone)), value)


def apply_radial_deadband(x: float, y: float, deadzone: float) -> tuple[float, float]:
    """Deadzone on the stick's distance from center, keeping its direction.

    A circular deadzone matters for swerve: the left stick says *which way* to
    go, and a square (per-axis) deadzone would bend shallow diagonals onto the
    axes.
    """
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone:
        return 0.0, 0.0
    scaled = min(1.0, (magnitude - deadzone) / (1.0 - deadzone))
    return x / magnitude * scaled, y / magnitude * scaled


def shape_inputs(left_x: float, left_y: float, right_x: float, *, drive_deadzone_pct: float,
                 drive_sensitivity_pct: float, turn_deadzone_pct: float,
                 turn_sensitivity_pct: float) -> tuple[float, float, float]:
    """Stick positions (-1 to 1, +y down as gamepads report it) -> (vx, vy, omega).

    Output is in the robot frame: +vx forward, +vy left, +omega counter-clockwise,
    each a fraction of the robot's maximum.
    """
    x, y = apply_radial_deadband(left_x, left_y, drive_deadzone_pct / 100.0)
    turn = apply_deadband(right_x, turn_deadzone_pct / 100.0)
    drive_gain = drive_sensitivity_pct / 100.0
    turn_gain = turn_sensitivity_pct / 100.0
    # Stick up is negative y -> forward; stick left is negative x -> +vy (left);
    # stick left is also counter-clockwise rotation.
    return -y * drive_gain, -x * drive_gain, -turn * turn_gain
