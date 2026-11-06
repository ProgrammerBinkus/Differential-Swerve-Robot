"""Robot main-loop safety rules, run against simulated hardware with an injected command stream."""

import pytest

from common.protocol import DriveCommand
from robot.robot import Mode, Robot

DT = 0.005


@pytest.fixture
def robot(tmp_path):
    bot = Robot(tmp_path / "robot_config.json", simulate=True, udp_port=0, tcp_port=0)
    bot.feed = None  # the next command the fake receiver returns
    bot._receiver.poll = lambda now: bot.feed
    bot.clock = 0.0
    yield bot
    bot._shutdown()


def run(robot, seconds, command=None):
    """Step the loop; ``command`` is delivered every step (None = the station is silent)."""
    for _ in range(int(seconds / DT)):
        robot.clock += DT
        robot.feed = command
        robot._step(robot.clock, DT)


def test_does_not_enable_until_the_station_has_sent_disabled(robot):
    run(robot, 0.1, DriveCommand(seq=1, enabled=True))
    assert robot._mode is Mode.DISABLED
    run(robot, 0.05, DriveCommand(seq=2, enabled=False))
    run(robot, 0.05, DriveCommand(seq=3, enabled=True))
    assert robot._mode is Mode.DRIVE


def test_watchdog_trip_needs_a_fresh_enable(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    assert robot._mode is Mode.DRIVE
    run(robot, 0.5)  # link drops
    assert robot._mode is Mode.DISABLED
    run(robot, 0.1, DriveCommand(seq=3, enabled=True))  # link back, station still says enabled
    assert robot._mode is Mode.DISABLED


def test_set_zero_is_ignored_while_enabled(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    offsets = {name: m["offset"] for name, m in robot.config["modules"].items()}
    run(robot, 0.05, DriveCommand(seq=3, enabled=True, zero_presses=1))
    assert {name: m["offset"] for name, m in robot.config["modules"].items()} == offsets


def test_set_zero_while_disabled_saves_offsets(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=False, zero_presses=1))
    raws = {m.name: m.raw for m in robot._drivetrain.modules}
    assert {name: m["offset"] for name, m in robot.config["modules"].items()} == raws


def test_mapping_change_rejected_while_enabled(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    result = robot._apply_config_update({"config": {"modules": {"FL": {"invert_a": True}}}})
    assert not result["ok"]


def test_config_message_carries_the_protocol_version(robot):
    from common.protocol import PROTOCOL_VERSION
    assert robot._config_message()["protocol"] == PROTOCOL_VERSION
