"""Driver station preferences, saved between sessions."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "station_settings.json"


# Allowed range of each number, matching the sliders.
RANGES = {
    "drive_sensitivity": (0.0, 100.0),
    "drive_deadzone": (0.0, 50.0),
    "turn_sensitivity": (0.0, 100.0),
    "turn_deadzone": (0.0, 50.0),
}


@dataclass
class StationSettings:
    robot_host: str = "orangepi.local"
    drive_sensitivity: float = 100.0  # percent of max speed at full left stick
    drive_deadzone: float = 8.0       # percent of stick travel ignored around center
    turn_sensitivity: float = 60.0    # percent of max rotation at full right stick
    turn_deadzone: float = 8.0

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "StationSettings":
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
            if isinstance(default, str) and isinstance(value, str) and value.strip():
                setattr(settings, field.name, value.strip())
            elif isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and math.isfinite(value):
                low, high = RANGES[field.name]
                setattr(settings, field.name, max(low, min(high, float(value))))
        return settings

    def save(self, path: Path = SETTINGS_PATH) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save %s: %s", path, exc)
