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
