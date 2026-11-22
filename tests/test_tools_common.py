"""Bring-up tools pause the robot program while they use the hardware, and start it again after."""

import subprocess

import pytest

from tools import _common


def test_a_running_robot_program_is_stopped_and_started_again(monkeypatch):
    log = []
    monkeypatch.setattr(_common.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(_common.subprocess, "run",
                        lambda args, **kw: (log.append(args), subprocess.CompletedProcess(args, 0))[1])
    with _common.robot_program_paused():
        assert log[-1] == ["sudo", "-n", "systemctl", "stop", _common.ROBOT_SERVICE]
    assert log[-1] == ["sudo", "-n", "systemctl", "start", _common.ROBOT_SERVICE]


def test_it_is_started_again_even_if_the_tool_fails(monkeypatch):
    log = []
    monkeypatch.setattr(_common.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(_common.subprocess, "run",
                        lambda args, **kw: (log.append(args), subprocess.CompletedProcess(args, 0))[1])
    with pytest.raises(RuntimeError):
        with _common.robot_program_paused():
            raise RuntimeError("tool crashed")
    assert log[-1][-2:] == ["start", _common.ROBOT_SERVICE]


def test_nothing_happens_when_the_robot_program_is_not_running(monkeypatch):
    log = []
    monkeypatch.setattr(_common.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(_common.subprocess, "run",
                        lambda args, **kw: (log.append(args), subprocess.CompletedProcess(args, 3))[1])
    with _common.robot_program_paused():
        pass
    assert all(args[0] != "sudo" for args in log)


def test_nothing_happens_off_the_pi(monkeypatch):
    monkeypatch.setattr(_common.shutil, "which", lambda name: None)
    monkeypatch.setattr(_common.subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    with _common.robot_program_paused():
        pass
