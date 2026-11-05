import pytest

from robot.swerve.mixing import RateLimiter, mix, steer_first_scale


def test_pure_drive_turns_both_motors_together():
    assert mix(0.5, 0.0) == (0.5, 0.5)


def test_pure_steer_turns_motors_opposite():
    assert mix(0.0, 0.3) == (0.3, -0.3)


def test_steer_first_scale_never_cuts_steering():
    plans = [(0.9, 0.3), (0.5, 0.0)]
    scale = steer_first_scale(plans)
    assert scale == pytest.approx(0.7 / 0.9)
    for drive, steer in plans:
        a, b = mix(drive * scale, steer)
        assert max(abs(a), abs(b)) <= 1.0 + 1e-9


def test_no_scaling_needed():
    assert steer_first_scale([(0.4, 0.2), (-0.5, -0.5)]) == 1.0


def test_rate_limiter():
    limiter = RateLimiter(rate_per_s=2.0)
    assert limiter.calculate(1.0, 0.1) == pytest.approx(0.2)
    assert limiter.calculate(1.0, 1.0) == pytest.approx(1.0)
    assert limiter.calculate(-1.0, 0.25) == pytest.approx(0.5)
