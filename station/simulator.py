"""The built-in robot simulator behind the "Simulator" connection mode.

It is the robot program itself (``robot --sim``), run as a hidden child
process that listens on localhost. It keeps its own config file in AppData,
so its zero offsets, mapping and tuning never mix with the real robot's.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
from pathlib import Path
from typing import IO, Optional

from common.protocol import UDP_PORT
from station.settings import DATA_DIR
from station.windows import IS_WINDOWS, LOG_DIR, ChildJob

log = logging.getLogger(__name__)

SIMULATOR_CONFIG_PATH = DATA_DIR / "simulator_config.json"
SIMULATOR_LOG_PATH = LOG_DIR / "simulator.log"
RUN_SIMULATOR_FLAG = "--run-simulator"   # the packaged app runs as the simulator when given this
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CREATE_NO_WINDOW = 0x08000000


def robot_ports_in_use() -> bool:
    """True if something on this computer (a simulator started by hand, say) already has the robot's port."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("", UDP_PORT))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def simulator_command(config_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, RUN_SIMULATOR_FLAG, "--config", str(config_path)]
    return [sys.executable, str(_PROJECT_ROOT / "main.py"), "robot", "--sim", "--config", str(config_path)]


class LocalSimulator:
    """Starts, watches and stops the simulator child process."""

    def __init__(self, config_path: Path = SIMULATOR_CONFIG_PATH) -> None:
        self._config_path = config_path
        self._process: Optional[subprocess.Popen] = None
        self._job: Optional[ChildJob] = None
        self._log_file: Optional[IO[bytes]] = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> str:
        """Start the simulator unless one is already running. Returns a message for the terminal."""
        if self.running:
            return "Built-in simulator already running"
        if robot_ports_in_use():
            return "Using the simulator already running on this computer"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        SIMULATOR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(SIMULATOR_LOG_PATH, "ab")
        self._process = subprocess.Popen(
            simulator_command(self._config_path), cwd=str(_PROJECT_ROOT), stdin=subprocess.DEVNULL,
            stdout=self._log_file, stderr=subprocess.STDOUT,
            creationflags=_CREATE_NO_WINDOW if IS_WINDOWS else 0,
        )
        self._job = ChildJob(int(self._process._handle)) if IS_WINDOWS else None
        log.info("Started the simulator (pid %d)", self._process.pid)
        return "Starting the built-in simulator"

    def check(self) -> Optional[str]:
        """A message if the simulator stopped on its own since the last check, else ``None``."""
        if self._process is None or self._process.poll() is None:
            return None
        code = self._process.returncode
        self._cleanup()
        return f"The built-in simulator stopped (exit code {code}). Details: {SIMULATOR_LOG_PATH}"

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            log.info("Stopped the simulator")
        self._cleanup()

    def _cleanup(self) -> None:
        if self._job is not None:
            self._job.close()  # also ends anything the simulator started
            self._job = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        self._process = None
