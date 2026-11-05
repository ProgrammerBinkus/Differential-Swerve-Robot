"""Shared helpers for the bring-up tools."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from common.config import ConfigError
from robot.config_store import ConfigStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict[str, Any]:
    try:
        return ConfigStore(path or PROJECT_ROOT / "robot_config.json").load()
    except ConfigError as exc:
        sys.exit(str(exc))


def confirm_wheels_off_ground() -> None:
    answer = input("Motors will move. Are all wheels off the ground? [y/N] ").strip().lower()
    if answer != "y":
        sys.exit("Cancelled.")
