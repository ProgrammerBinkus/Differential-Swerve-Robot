import math

import pytest

from robot.swerve.steering_angle import SteeringAngleTracker

COUNTS = 16384


def degrees(tracker):
    return math.degrees(tracker.angle_rad)


def test_encoder_quarter_turn_is_45_degrees_of_steering():
    tracker = SteeringAngleTracker()
    tracker.update(COUNTS // 4)
    assert degrees(tracker) == pytest.approx(45.0)


def test_start_up_picks_the_solution_within_90_degrees():
    tracker = SteeringAngleTracker()
    tracker.update(COUNTS - COUNTS // 8)  # encoder at 315 degrees
    assert degrees(tracker) == pytest.approx(-22.5)


def test_offset_is_subtracted():
    tracker = SteeringAngleTracker(offset=1000)
    tracker.update(1000)
    assert degrees(tracker) == pytest.approx(0.0)


def test_unwrapping_counts_full_turns():
    tracker = SteeringAngleTracker()
    raw = 0
    tracker.update(raw)
    step = COUNTS // 10
    for _ in range(25):  # 2.5 encoder turns = 450 degrees of steering
        raw = (raw + step) % COUNTS
        tracker.update(raw)
    assert degrees(tracker) == pytest.approx(25 * step * 360 / COUNTS / 2)


def test_unwrapping_backwards_across_zero():
    tracker = SteeringAngleTracker()
    tracker.update(100)
    tracker.update(COUNTS - 100)  # a 200-count step backwards across zero: +100 -> -100
    assert degrees(tracker) == pytest.approx(-100 * 360 / COUNTS / 2)


def test_invert_flips_direction():
    tracker = SteeringAngleTracker(invert=True)
    tracker.update(COUNTS // 4)
    assert degrees(tracker) == pytest.approx(-45.0)


def test_zero_here():
    tracker = SteeringAngleTracker()
    tracker.update(5000)
    assert tracker.zero_here() == 5000
    assert degrees(tracker) == 0.0
    tracker.update(5000 + COUNTS // 4)
    assert degrees(tracker) == pytest.approx(45.0)
