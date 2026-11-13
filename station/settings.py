"""Driver station preferences, saved between sessions."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from station import APP_NAME

log = logging.getLogger(__name__)

# Per-user and writable even when the app is installed under Program Files.
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
SETTINGS_PATH = DATA_DIR / "settings.json"
# Where versions before the Windows app kept them; read once if nothing is saved yet.
LEGACY_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "station_settings.json"


CONNECTIONS = ("robot", "simulator")
VIEWS = ("robot", "field")

# Allowed range of each number, matching the sliders.
RANGES = {
    "drive_sensitivity": (0.0, 100.0),
    "drive_deadzone": (0.0, 50.0),
    "turn_sensitivity": (0.0, 100.0),
    "turn_deadzone": (0.0, 50.0),
}


@dataclass
class StationSettings:
    robot_host: str = "orangepi4pro.local"  # the Orange Pi 4 Pro image's own hostname
    drive_sensitivity: float = 100.0  # percent of max speed at full left stick
    drive_deadzone: float = 8.0       # percent of stick travel ignored around center
    turn_sensitivity: float = 60.0    # percent of max rotation at full right stick
    turn_deadzone: float = 8.0
    keyboard_control: bool = False    # drive with W A S D / arrows and J L
    connection: str = "robot"         # "robot" or "simulator" (the built-in one)
    view: str = "robot"               # drawing on the Drive tab: "robot" (electronics) or "field" (motion)

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "StationSettings":
        if path == SETTINGS_PATH and not path.exists() and LEGACY_SETTINGS_PATH.exists():
            path = LEGACY_SETTINGS_PATH
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable %s: %s", path, exc)
            return cls()
        settings = cls()
        if not isinstance(stored, dict):
            return settings
        for field in fields(cls):
            value = stored.get(field.name)
            default = getattr(settings, field.name)
            if isinstance(default, bool):
                if isinstance(value, bool):
                    setattr(settings, field.name, value)
            elif field.name == "connection":
                if value in CONNECTIONS:
                    settings.connection = value
            elif field.name == "view":
                if value in VIEWS:
                    settings.view = value
            elif isinstance(default, str) and isinstance(value, str) and value.strip():
                setattr(settings, field.name, value.strip())
            elif isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and math.isfinite(value):
                low, high = RANGES[field.name]
                setattr(settings, field.name, max(low, min(high, float(value))))
        return settings

    def save(self, path: Path = SETTINGS_PATH) -> None:
        """Write the settings now. Atomic: a crash mid-save keeps the previous file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            log.warning("Could not save %s: %s", path, exc)
