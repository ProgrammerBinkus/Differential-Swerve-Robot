"""Loads and saves the robot configuration file."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from common.config import ConfigError, deep_update, default_config, validate_config

log = logging.getLogger(__name__)


class ConfigStore:
    """Reads ``robot_config.json`` and writes it back safely.

    Saving writes a temporary file and renames it over the old one, so a power
    cut mid-save never leaves a half-written file. The previous version is kept
    next to it as ``robot_config.json.bak``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        """Return the stored configuration, filled in with defaults for any missing keys.

        Raises :class:`ConfigError` if the file exists but is unreadable or
        invalid; the robot refuses to drive on a configuration it cannot trust.
        """
        config = default_config()
        if not self.path.exists():
            log.info("No config file at %s, writing defaults", self.path)
            self.save(config)
            return config

        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Cannot read {self.path}: {exc}") from exc
        if not isinstance(stored, dict):
            raise ConfigError(f"{self.path} does not contain a JSON object")

        deep_update(config, stored)
        errors = validate_config(config)
        if errors:
            raise ConfigError(f"{self.path} is invalid:\n  " + "\n  ".join(errors))
        return config

    def save(self, config: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(temporary, "w", encoding="utf-8") as file:
            file.write(json.dumps(config, indent=2) + "\n")
            file.flush()
            os.fsync(file.fileno())  # on disk before the rename, or a power cut can leave an empty file
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        os.replace(temporary, self.path)
