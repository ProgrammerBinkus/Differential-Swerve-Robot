"""Heading tracking, the IMU wrapper, simulated rotation and field-relative drive."""

import math

import pytest

from common.config import default_config
from common.protocol import DriveCommand
from robot.hardware import open_hardware
from robot.hardware.imu import HeadingTracker, Imu, wrap_degrees
from robot.robot import Robot
from robot.swerve.drivetrain import Drivetrain

DT = 0.005


def feed(tracker, rate, seconds):
    for _ in range(round(seconds / DT)):
        tracker.add_sample(rate, DT)


def test_bias_is_measured_at_rest_and_removed():
    tracker = HeadingTracker(calibration_s=1.0)
    feed(tracker, 0.8, 1.0)                      # a gyro that reads 0.8 deg/s while still
    assert tracker.ready
    assert tracker.bias_dps == pytest.approx(0.8)
    feed(tracker, 0.8 + 30.0, 2.0)               # turning 30 deg/s counter-clockwise for 2 s
    assert tracker.heading_deg == pytest.approx(60.0, abs=0.01)


def test_calibration_restarts_if_the_robot_moves():
    tracker = HeadingTracker(calibration_s=1.0)
    feed(tracker, 0.0, 0.6)
    feed(tracker, 25.0, 0.1)                     # bumped
    feed(tracker, 0.0, 0.6)
    assert not tracker.ready                     # 0.6 s of stillness since the bump is not enough
    feed(tracker, 0.0, 0.5)
    assert tracker.ready


@pytest.mark.parametrize("facing, expected", [(0, 0), (90, 90), (180, -180), (-90, -90)])
def test_set_field_forward(facing, expected):
    tracker = HeadingTracker(calibration_s=0.1)
    feed(tracker, 0.0, 0.1)
    feed(tracker, 45.0, 1.0)                     # robot has turned 45 degrees
    tracker.set_field_forward(facing)
    assert tracker.heading_deg == pytest.approx(expected)
    feed(tracker, 10.0, 1.0)
    assert tracker.heading_deg == pytest.approx(wrap_degrees(expected + 10))


class FlakyGyro:
    bus_path = "test"

    def __init__(self):
        self.fail = False

    def read_rate_dps(self):
        if self.fail:
            raise OSError("bus error")
        return 0.0

    def read_sample(self):
        return {"accel": [0, 0, 1]}

    def close(self):
        pass


def test_imu_faults_and_recalibrates_after_recovering():
    gyro = FlakyGyro()
    imu = Imu(gyro, tracker=HeadingTracker(calibration_s=0.1))
    for _ in range(40):
        imu.update(DT)
    assert imu.status == "ok"
    gyro.fail = True
    for _ in range(Imu.MAX_CONSECUTIVE_READ_ERRORS):
        imu.update(DT)
    assert imu.status == "fault" and imu.heading_deg is None
    gyro.fail = False
    imu.update(DT)
    assert imu.status == "calibrating"           # the heading may have changed unseen


def test_absent_imu_never_gives_a_heading():
    imu = Imu(None)
    imu.update(DT)
    assert imu.status == "absent" and imu.heading_deg is None and not imu.set_field_forward(0)


def test_invert_yaw_flips_the_heading():
    class Gyro(FlakyGyro):
        rate = 0.0

        def read_rate_dps(self):
            return self.rate
    gyro = Gyro()
    imu = Imu(gyro, invert_yaw=True, tracker=HeadingTracker(calibration_s=0.1))
    for _ in range(round(0.1 / DT)):
        imu.update(DT)                           # still while it calibrates
    gyro.rate = 20.0                             # board upside down: it reports counter-clockwise turning...
    for _ in range(round(1.0 / DT)):
        imu.update(DT)
    assert imu.heading_deg == pytest.approx(-20.0, abs=0.2)  # ...that is really clockwise


# --------------------------------------------------------------- with the simulator

@pytest.fixture
def sim():
    config = default_config()
    hardware = open_hardware(config, simulate=True)
    drivetrain = Drivetrain.from_config(hardware, config)
    return hardware, drivetrain


def run(sim, seconds, action):
    hardware, drivetrain = sim
    for _ in range(round(seconds / DT)):
        hardware.step(DT)
        drivetrain.read_sensors()
        hardware.imu.update(DT)
        action(drivetrain)


def test_simulated_chassis_turns_and_the_gyro_sees_it(sim):
    hardware, _ = sim
    run(sim, 2.0, lambda d: None)                # still: the gyro calibrates
    assert hardware.imu.status == "ok"
    run(sim, 1.0, lambda d: d.drive(0.0, 0.0, 0.05))   # slow, so the heading stays well inside +/-180
    assert 5 < hardware.imu.heading_deg < 90     # counter-clockwise
    assert hardware.imu.telemetry()["rate"] > 0


def test_field_relative_forward_is_away_from_the_driver(sim):
    hardware, _ = sim
    run(sim, 2.0, lambda d: None)
    hardware.imu.set_field_forward(90)           # the robot faces the driver's left
    run(sim, 1.5, lambda d: d.drive(1.0, 0.0, 0.0, hardware.imu.heading_deg))
    for module in sim[1].modules:                # so "away from the driver" is the robot's right: -90 degrees
        error = math.remainder(math.degrees(module.angle_rad) + 90, 180)
        assert abs(error) < 4


def test_robot_set_field_forward_request(tmp_path):
    robot = Robot(tmp_path / "cfg.json", simulate=True, udp_port=0, tcp_port=0)
    robot._receiver.poll = lambda now: DriveCommand(seq=1)
    try:
        early = robot._set_field_forward({"facing_deg": 0})
        assert not early["ok"]                   # still calibrating
        for i in range(round(2.0 / DT)):
            robot._step(i * DT, DT)
        assert robot._set_field_forward({"facing_deg": 180})["ok"]
        assert robot._hardware.imu.heading_deg == pytest.approx(-180.0, abs=0.5)
        assert not robot._set_field_forward({"facing_deg": "north"})["ok"]
    finally:
        robot._shutdown()
