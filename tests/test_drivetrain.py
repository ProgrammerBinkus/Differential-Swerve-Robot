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


def test_full_turn_stick_is_capped_at_the_turn_rate_limit():
    config = default_config()
    radius = math.hypot(0.11, 0.11)
    config["tuning"].update(max_speed_mps=10.0, max_turn_dps=360.0)
    fast = Drivetrain.from_config(open_hardware(config, simulate=True), config)
    assert math.degrees(fast.max_omega_rad_s) == pytest.approx(360.0)   # not the 3,680 deg/s the wheels could do
    config["tuning"].update(max_speed_mps=0.5)
    slow = Drivetrain.from_config(open_hardware(config, simulate=True), config)
    assert slow.max_omega_rad_s == pytest.approx(0.5 / radius)          # wheels are the limit: about 184 deg/s


def test_spinning_at_top_speed_stays_inside_the_gyro_range():
    config = default_config()
    config["tuning"].update(max_speed_mps=10.0, max_turn_dps=1440.0, steer_limit=1.0)
    hardware = open_hardware(config, simulate=True)
    drivetrain = Drivetrain.from_config(hardware, config)
    drivetrain.read_sensors()
    fastest = 0.0
    for _ in range(int(3.0 / DT)):
        hardware.step(DT)
        drivetrain.read_sensors()
        drivetrain.drive(0.0, 0.0, 1.0)
        fastest = max(fastest, abs(hardware.imu._source.read_rate_dps()))
    assert 1300.0 < fastest < 2000.0        # reaches the limit it was given, below the gyro's +/-2000


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


def test_rezero_skips_a_faulted_module(rig):
    hardware, drivetrain = rig
    hardware.encoders["E2"].fail = True  # FL
    run(rig, 0.1, lambda d: None)
    assert "FL" not in drivetrain.rezero()


def test_home_never_reports_done_with_no_working_encoders(rig):
    hardware, drivetrain = rig
    for encoder in hardware.encoders.values():
        encoder.fail = True
    run(rig, 0.1, lambda d: None)
    assert not drivetrain.any_ready
    assert drivetrain.home() is False
