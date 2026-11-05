"""Start the driver station: ``python -m station`` (also the packaged app's entry point)."""

from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk

from station import APP_NAME, __version__
from station import windows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="station", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--host", help="robot hostname or IP for this session (default: the saved address)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = parser.parse_args(argv)

    windows.configure_logging()
    windows.install_crash_handler()
    windows.prepare_process()
    log = logging.getLogger("station")

    instance = windows.SingleInstance()
    if instance.already_running:
        log.info("Already running; bringing the open window forward")
        instance.focus_existing_window(APP_NAME)
        return 0

    from station.app import StationApp
    from station.settings import StationSettings

    log.info("%s %s starting", APP_NAME, __version__)
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda *exc_info: log.error("Error in the UI", exc_info=exc_info)
        StationApp(root, StationSettings.load(), host=args.host)  # --host is for this session only
        root.mainloop()
    finally:
        instance.release()
    log.info("%s closed", APP_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
