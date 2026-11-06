"""The simulated field position and the field view's geometry."""

import json

import pytest

from common.protocol import DriveCommand
from robot.robot import Robot
from station.settings import StationSettings
from station.views.field_view import robot_to_field

DT = 0.005


def test_robot_to_field_rotates_by_heading():
    # Robot at (1, 2) facing the driver's left (90 degrees): its forward is field +y.
    assert robot_to_field(1.0, 0.0, (1.0, 2.0), 90.0) == pytest.approx((1.0, 3.0))
    assert robot_to_field(0.0, 1.0, (0.0, 0.0), 90.0) == pytest.approx((-1.0, 0.0))


@pytest.fixture
def robot(tmp_path):
    bot = Robot(tmp_path / "cfg.json", simulate=True, udp_port=0, tcp_port=0)
    bot.feed = DriveCommand(seq=1)
    bot._receiver.poll = lambda now: bot.feed
    bot.clock = 0.0
    yield bot
    bot._shutdown()


def run(robot, seconds, **command):
    robot.feed = DriveCommand(seq=1, **command)
    for _ in range(round(seconds / DT)):
        robot.clock += DT
        robot._step(robot.clock, DT)


def test_simulated_robot_moves_on_the_field(robot):
    run(robot, 2.0)                                   # still: gyro calibrates
    run(robot, 0.1, enabled=False)
    run(robot, 2.0, enabled=True, vx=0.5)             # robot-relative forward, robot facing away
    assert robot._pose_x > 0.3 and abs(robot._pose_y) < 0.05


def test_position_is_in_the_field_frame(robot):
    robot.config["field_relative"] = True
    run(robot, 2.0)
    robot._set_field_forward({"facing_deg": 90})      # the robot faces the driver's left
    run(robot, 0.1, enabled=False)
    run(robot, 2.0, enabled=True, vx=0.5)             # field forward: away from the driver
    assert robot._pose_x > 0.3 and abs(robot._pose_y) < 0.1


def test_set_field_forward_starts_a_new_frame(robot):
    run(robot, 2.0)
    run(robot, 0.1, enabled=False)
    run(robot, 1.0, enabled=True, vy=0.5)
    epoch = robot._pose_epoch
    robot._set_field_forward({"facing_deg": 0})
    assert (robot._pose_x, robot._pose_y, robot._pose_epoch) == (0.0, 0.0, epoch + 1)


def test_view_setting_is_validated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"view": "field"}))
    assert StationSettings.load(path).view == "field"
    path.write_text(json.dumps({"view": "map"}))
    assert StationSettings.load(path).view == "robot"
