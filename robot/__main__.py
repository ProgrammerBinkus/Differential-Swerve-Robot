"""Start the robot: ``python -m robot`` (add ``--sim`` to run without hardware)."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from common.config import ConfigError
from robot.hardware import HardwareError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="robot", description="Differential swerve robot control loop.")
    parser.add_argument("--sim", action="store_true", help="simulate motors and encoders (no hardware needed)")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "robot_config.json",
                        help="configuration file (default: robot_config.json in the project folder)")
    parser.add_argument("--verbose", action="store_true", help="log debug messages")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # Imported here so --help works on a machine without wpimath installed.
    from robot.robot import Robot

    try:
        robot = Robot(args.config, simulate=args.sim)
    except (ConfigError, HardwareError, OSError) as exc:
        logging.getLogger("robot").error("%s", exc)
        return 1

    def stop(signum, frame):
        robot.request_stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    robot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
