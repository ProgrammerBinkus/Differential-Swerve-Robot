"""The motor check, run on the simulated robot: each motor alone must turn its module."""

from common.protocol import DriveCommand
from robot.robot import Mode
from robot.swerve.motor_check import MotorCheck
from tests.test_robot import robot, run  # noqa: F401  (the fixture)

MOTORS = [f"M{n}" for n in range(1, 9)]
CHECK_S = 8 * (2 * MotorCheck.SETTLE_S + MotorCheck.PULSE_S) + 0.2


def _enable(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    run(robot, 0.05, DriveCommand(seq=2, enabled=True))
    assert robot._mode is Mode.DRIVE


def _results(robot):
    return robot._check.telemetry()["results"]


def test_every_working_motor_passes_and_the_robot_goes_back_to_driving(robot):
    _enable(robot)
    assert robot._start_check({"tag": "check"}, robot.clock)["ok"]
    assert robot._mode is Mode.CHECKING
    run(robot, CHECK_S, DriveCommand(seq=3, enabled=True))
    results = _results(robot)
    assert sorted(results) == MOTORS
    assert all(r["ok"] for r in results.values()), results
    assert all(abs(r["moved"]) >= MotorCheck.MIN_MOVE_DEG for r in results.values())
    assert robot._mode is Mode.DRIVE
    assert robot._check.state == "done"


def test_a_dead_motor_is_reported_and_the_others_still_pass(robot):
    dead = robot._hardware.output_for_motor(robot.config, "M3")
    dead.set = lambda command: None          # a cut lead: commands go nowhere
    _enable(robot)
    robot._start_check({"tag": "check"}, robot.clock)
    run(robot, CHECK_S, DriveCommand(seq=3, enabled=True))
    results = _results(robot)
    assert results["M3"]["ok"] is False
    assert all(results[m]["ok"] for m in MOTORS if m != "M3")


def test_disabling_stops_the_check_at_once(robot):
    _enable(robot)
    robot._start_check({"tag": "check"}, robot.clock)
    run(robot, 1.5, DriveCommand(seq=3, enabled=True))
    run(robot, 0.05, DriveCommand(seq=4, enabled=False))
    assert robot._mode is Mode.DISABLED
    assert robot._check.state == "aborted"
    assert all(o.braking for o in robot._hardware.outputs.values())
    not_checked = [m for m, r in _results(robot).items() if r["ok"] is None]
    assert not_checked and all("disabled" in _results(robot)[m]["note"] for m in not_checked)


def test_the_check_needs_the_robot_enabled_and_the_sticks_centered(robot):
    run(robot, 0.05, DriveCommand(seq=1, enabled=False))
    assert not robot._start_check({"tag": "check"}, robot.clock)["ok"]
    run(robot, 0.05, DriveCommand(seq=2, enabled=True, vx=0.5))
    assert not robot._start_check({"tag": "check"}, robot.clock)["ok"]
    assert robot._mode is Mode.DRIVE


def test_telemetry_carries_the_check(robot):
    sent = []
    robot._receiver.send_telemetry = sent.append
    _enable(robot)
    robot._send_telemetry()
    assert sent[-1]["check"] is None
    robot._start_check({"tag": "check"}, robot.clock)
    robot._send_telemetry()
    assert sent[-1]["check"]["state"] == "running" and sent[-1]["check"]["current"] in MOTORS
