import math

import pytest

from station.shaping import apply_deadband, apply_radial_deadband, shape_inputs

FULL = dict(drive_deadzone_pct=10, drive_sensitivity_pct=100, turn_deadzone_pct=10, turn_sensitivity_pct=100)


def test_deadband():
    assert apply_deadband(0.05, 0.1) == 0.0
    assert apply_deadband(1.0, 0.1) == 1.0
    assert apply_deadband(-0.55, 0.1) == pytest.approx(-0.5)


def test_radial_deadband_keeps_direction():
    x, y = apply_radial_deadband(0.6, 0.3, 0.1)
    assert math.atan2(y, x) == pytest.approx(math.atan2(0.3, 0.6))


def test_stick_up_drives_forward():
    vx, vy, omega = shape_inputs(0.0, -1.0, 0.0, **FULL)
    assert (vx, vy, omega) == pytest.approx((1.0, 0.0, 0.0))


def test_stick_left_strafes_left_and_turns_counter_clockwise():
    vx, vy, _ = shape_inputs(-1.0, 0.0, 0.0, **FULL)
    _, _, omega = shape_inputs(0.0, 0.0, -1.0, **FULL)
    assert vy == pytest.approx(1.0)
    assert omega == pytest.approx(1.0)


def test_sensitivity_scales_output():
    settings = dict(FULL, turn_sensitivity_pct=50)
    _, _, omega = shape_inputs(0.0, 0.0, 1.0, **settings)
    assert omega == pytest.approx(-0.5)
