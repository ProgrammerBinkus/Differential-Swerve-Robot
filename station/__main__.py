"""Start the driver station: ``python -m station``."""

from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk


def _enable_sharp_text_on_windows() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="station", description="Differential swerve driver station.")
    parser.add_argument("--host", help="robot hostname or IP (default: last one used, or orangepi.local)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    from station.app import StationApp
    from station.settings import StationSettings

    _enable_sharp_text_on_windows()
    settings = StationSettings.load()
    if args.host:
        settings.robot_host = args.host
    root = tk.Tk()
    StationApp(root, settings)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
