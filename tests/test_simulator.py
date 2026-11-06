import sys
from pathlib import Path

from station.simulator import RUN_SIMULATOR_FLAG, simulator_command


def test_source_run_starts_the_robot_program_in_sim_mode(tmp_path):
    command = simulator_command(tmp_path / "sim.json")
    assert command[0] == sys.executable
    assert Path(command[1]).name == "main.py"
    assert command[2:4] == ["robot", "--sim"]
    assert command[-2:] == ["--config", str(tmp_path / "sim.json")]


def test_packaged_app_runs_itself_as_the_simulator(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = simulator_command(tmp_path / "sim.json")
    assert command[:2] == [sys.executable, RUN_SIMULATOR_FLAG]


def test_a_failed_launch_reports_instead_of_crashing(tmp_path, monkeypatch):
    import subprocess

    from station import simulator
    monkeypatch.setattr(simulator, "robot_ports_in_use", lambda: False)
    monkeypatch.setattr(simulator, "SIMULATOR_LOG_PATH", tmp_path / "sim.log")

    def refuse(*args, **kwargs):
        raise FileNotFoundError("python.exe not found")
    monkeypatch.setattr(subprocess, "Popen", refuse)
    sim = simulator.LocalSimulator(tmp_path / "sim.json")
    message = sim.start()
    assert message.startswith(simulator.START_FAILED)
    assert not sim.running
