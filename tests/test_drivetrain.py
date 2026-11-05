"""Drivetrain behavior against the simulated plant (no hardware needed)."""

import math

import pytest

from common.config import default_config
from robot.hardware import open_hardware
from robot.swerve.drivetrain import Drivetrain

DT = 0.005


@pytest.fixture
def rig():
    config = default_config()
    hardware = open_hardware(config, simulate=True)
    drivetrain = Drivetrain.from_config(hardware, config)
    drivetrain.read_sensors()
    return hardware, drivetrain


def run(rig, seconds, action):
    hardware, drivetrain = rig
    for _ in range(int(seconds / DT)):
        hardware.step(DT)
        drivetrain.read_sensors()
        action(drivetrain)


def angles(drivetrain):
    return {m.name: math.degrees(math.remainder(m.angle_rad, 2 * math.pi)) for m in drivetrain.modules}


def facing(angle_deg, target_deg):
    """True if the wheel lies along target (either way round, since optimize may reverse it)."""
    error = math.remainder(math.radians(angle_deg - target_deg), math.pi)
    return abs(math.degrees(error)) < 3.0


def test_strafe_left_points_every_wheel_sideways(rig):
    run(rig, 2.0, lambda d: d.drive(0.0, 1.0, 0.0))
    assert all(facing(a, 90.0) for a in angles(rig[1]).values())


def test_rotation_points_wheels_tangentially(rig):
    run(rig, 2.0, lambda d: d.drive(0.0, 0.0, 1.0))
    result = angles(rig[1])
    for name, expected in {"FL": 135, "FR": 45, "BL": -135, "BR": -45}.items():
        assert facing(result[name], expected), (name, result[name])


def test_driving_straight_runs_both_motors_together_once_aligned(rig):
    run(rig, 2.0, lambda d: d.drive(0.5, 0.0, 0.0))
    for module in rig[1].modules:
        assert abs(module.steer) < 0.05
        assert abs(module.drive) == pytest.approx(0.5, abs=0.01)


def test_motor_commands_stay_within_limits(rig):
    seen = []
    run(rig, 1.0, lambda d: (d.drive(1.0, 1.0, 1.0), seen.extend(abs(x) for m in d.modules
                                                                 for x in m.telemetry()["motors"])))
    assert max(seen) <= 1.0 + 1e-9


def test_home_returns_to_true_zero(rig):
    run(rig, 1.5, lambda d: d.drive(0.0, 1.0, 0.0))
    done = []
    run(rig, 3.0, lambda d: done.append(d.home()))
    assert done[-1]
    assert all(abs(a) < 3.5 for a in angles(rig[1]).values())


def test_wheels_hold_their_angle_when_stick_released(rig):
    run(rig, 1.5, lambda d: d.drive(0.0, 1.0, 0.0))
    before = angles(rig[1])
    run(rig, 1.0, lambda d: d.drive(0.0, 0.0, 0.0))
    after = angles(rig[1])
    for name in before:
        assert after[name] == pytest.approx(before[name], abs=2.0)


def test_encoder_failure_stops_module(rig):
    hardware, drivetrain = rig
    hardware.encoders["E2"].fail = True  # FL's encoder
    run(rig, 0.2, lambda d: d.drive(0.5, 0.0, 0.0))
    fl = drivetrain.modules[0]
    assert fl.fault
    assert (fl.drive, fl.steer) == (0.0, 0.0)
