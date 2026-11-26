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


def outputs(robot):
    return robot._hardware.outputs.values()


def test_disable_brakes_then_coasts(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    assert not any(o.braking for o in outputs(robot))          # never enabled: coasting, not braking
    run(robot, 0.2, DriveCommand(seq=2, enabled=True, vx=0.5))
    run(robot, 0.05, DriveCommand(seq=3, enabled=False))       # driver disables
    assert all(o.braking for o in outputs(robot))
    run(robot, Robot.BRAKE_HOLD_S + 0.1, DriveCommand(seq=4, enabled=False))
    assert not any(o.braking for o in outputs(robot))          # released so the wheels turn by hand


def test_watchdog_trip_brakes(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.2, DriveCommand(seq=2, enabled=True, vx=0.5))
    run(robot, 0.5)                                            # link lost
    assert robot._mode is Mode.DISABLED
    assert all(o.braking for o in outputs(robot))


def _count_homing(robot):
    calls = []
    original = robot._home_before_exit
    robot._home_before_exit = lambda: (calls.append(1), original())
    return calls


def test_stopping_while_disabled_does_not_move_the_wheels(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    calls = _count_homing(robot)
    robot._shutdown()
    assert calls == []
    assert all(o.output == 0.0 for o in outputs(robot))


def test_stopping_while_enabled_returns_the_wheels_to_zero(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    calls = _count_homing(robot)
    robot._shutdown()
    assert calls == [1]


def _power_off_runs(robot, monkeypatch, returncode=0, stderr=""):
    import subprocess

    import robot.robot as robot_module
    calls = []
    monkeypatch.setattr(robot_module.subprocess, "run", lambda args, **kw: (
        calls.append(args), subprocess.CompletedProcess(args, returncode, "", stderr))[1])
    robot._hardware._plant = None   # pretend to be the real Pi (the simulator refuses)
    return calls


def test_power_off_runs_systemctl_poweroff_while_disabled(robot, monkeypatch):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    calls = _power_off_runs(robot, monkeypatch)
    assert robot._power_off({"tag": "power"})["ok"]
    assert calls == [["sudo", "-n", "/usr/bin/systemctl", "poweroff"]]


def test_power_off_is_refused_while_enabled(robot, monkeypatch):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    calls = _power_off_runs(robot, monkeypatch)
    assert not robot._power_off({"tag": "power"})["ok"]
    assert calls == []


def test_power_off_is_refused_by_the_simulator(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    result = robot._power_off({"tag": "power"})
    assert not result["ok"] and "simulator" in result["message"]


def test_power_off_reports_a_missing_permission(robot, monkeypatch):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    _power_off_runs(robot, monkeypatch, returncode=1, stderr="sudo: a password is required")
    result = robot._power_off({"tag": "power"})
    assert not result["ok"] and "password is required" in result["message"] and "sudoers.sh" in result["message"]


def test_braking_keeps_the_steering_angles(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 1.0, DriveCommand(seq=2, enabled=True, vy=0.5))  # wheels sideways
    before = [m.angle_rad for m in robot._drivetrain.modules]
    run(robot, 1.0, DriveCommand(seq=3, enabled=False))
    after = [m.angle_rad for m in robot._drivetrain.modules]
    assert after == pytest.approx(before, abs=0.05)


def test_stop_request_ends_the_loop_promptly(robot):
    """SIGTERM (systemctl stop) must end the program, not hang until systemd kills it."""
    import threading
    import time as _time
    worker = threading.Thread(target=robot.run, daemon=True)
    worker.start()
    _time.sleep(0.1)
    for _ in range(50):          # hammer it: the old Event-based stop could deadlock here
        robot.request_stop()
    worker.join(timeout=3.0)
    assert not worker.is_alive()


def test_brake_time_after_disable_is_a_setting(robot):
    robot.config["tuning"]["disable_brake_s"] = 1.0
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    run(robot, 0.05, DriveCommand(seq=3, enabled=False))
    assert all(o.braking for o in outputs(robot))
    run(robot, 1.1, DriveCommand(seq=4, enabled=False))
    assert not any(o.braking for o in outputs(robot))          # coasting after 1 s, not 15
