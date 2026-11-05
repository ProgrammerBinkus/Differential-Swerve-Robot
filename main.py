"""Launcher for both halves of the project.

    python main.py station            driver station (laptop)
    python main.py robot              robot control loop (Orange Pi)
    python main.py robot --sim        robot control loop with simulated hardware

Anything after the first word is passed on, e.g. ``python main.py station --host 192.168.1.40``.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("robot", "station"):
        print(__doc__.strip())
        return 2
    target, rest = sys.argv[1], sys.argv[2:]
    if target == "robot":
        from robot.__main__ import main as run
    else:
        from station.__main__ import main as run
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
