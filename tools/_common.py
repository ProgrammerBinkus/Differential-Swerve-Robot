"""Shared helpers for the bring-up tools."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

from common.config import ConfigError
from robot.config_store import ConfigStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROBOT_SERVICE = "swerve-robot.service"


def load_config(path: Path | None = None) -> dict[str, Any]:
    try:
        return ConfigStore(path or PROJECT_ROOT / "robot_config.json").load()
    except ConfigError as exc:
        sys.exit(str(exc))


def confirm_wheels_off_ground() -> None:
    answer = input("Motors will move. Are all wheels off the ground? [y/N] ").strip().lower()
    if answer != "y":
        sys.exit("Cancelled.")


def _service_active() -> bool:
    if shutil.which("systemctl") is None:
        return False  # not the Pi (or no systemd): nothing to pause
    return subprocess.run(["systemctl", "is-active", "--quiet", ROBOT_SERVICE]).returncode == 0


@contextlib.contextmanager
def robot_program_paused() -> Iterator[None]:
    """Stop the robot program while a tool uses the motors or pins, then start it again.

    While it runs, the robot program holds every PWM channel and direction pin: a tool opening
    them would fail, or fight it, and closing them afterwards would pull them out from under it.
    The ``orangepi`` user may stop and start this one service without a password (pi_setup/finish.sh).
    """
    if not _service_active():
        yield
        return
    print(f"Pausing the robot program ({ROBOT_SERVICE}) while this runs ...")
    if subprocess.run(["sudo", "-n", "systemctl", "stop", ROBOT_SERVICE]).returncode != 0:
        sys.exit(f"Couldn't stop {ROBOT_SERVICE}. Stop it with: sudo systemctl stop {ROBOT_SERVICE}")
    try:
        yield
    finally:
        if subprocess.run(["sudo", "-n", "systemctl", "start", ROBOT_SERVICE]).returncode == 0:
            print("Robot program started again.")
        else:
            print(f"Couldn't restart it. Start it with: sudo systemctl start {ROBOT_SERVICE}")
