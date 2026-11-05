"""Windows integration: app identity, single instance, logging, crash reports and bundled files.

Everything here is a no-op on other platforms, so the station still runs from
source anywhere for development.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from common.timing import request_steady_timers
from station import APP_ID, APP_NAME

IS_WINDOWS = sys.platform == "win32"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME / "logs"
LOG_PATH = LOG_DIR / "station.log"

_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9

log = logging.getLogger(__name__)


def resource_path(name: str) -> Path:
    """A bundled file: next to the code when run from source, inside the bundle when frozen."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def configure_logging() -> None:
    """Log to a rotating file (the packaged app has no console) and to stderr when there is one."""
    handlers: list[logging.Handler] = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3,
                                                             encoding="utf-8"))
    except OSError:
        pass  # a read-only profile must not stop the app from starting
    if sys.stderr is not None:  # None in a windowed (no-console) build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def show_error(title: str, message: str) -> None:
    """A native message box, usable before Tk exists or after it has failed."""
    if IS_WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # MB_ICONERROR
    else:
        print(f"{title}: {message}", file=sys.stderr)


def install_crash_handler() -> None:
    """Log any uncaught exception and tell the user where the log is."""
    def handle(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("station").critical("Unhandled error", exc_info=(exc_type, exc, tb))
        show_error(APP_NAME, f"{APP_NAME} hit an unexpected error and has to close:\n\n{exc}\n\n"
                             f"Details are in {LOG_PATH}")

    sys.excepthook = handle


def prepare_process() -> None:
    """Steady timers, sharp text on high-DPI screens, and our own taskbar icon instead of Python's."""
    request_steady_timers()
    if not IS_WINDOWS:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


class ChildJob:
    """Puts a child process in a Windows job object that is killed when this process exits.

    That covers every way the station can end, including a crash or Task
    Manager, so a simulator child can never be left running on its own.
    :meth:`close` ends the child (and anything it started) right away.
    """

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    def __init__(self, process_handle: int) -> None:
        self._job: Optional[int] = None
        if not IS_WINDOWS:
            return
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32 = kernel32

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            log.warning("Could not create a job object (error %d)", ctypes.get_last_error())
            return
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not (kernel32.SetInformationJobObject(job, self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                 ctypes.byref(limits), ctypes.sizeof(limits))
                and kernel32.AssignProcessToJobObject(job, process_handle)):
            log.warning("Could not tie the simulator to the station (error %d)", ctypes.get_last_error())
            kernel32.CloseHandle(job)
            return
        self._job = job

    def close(self) -> None:
        if self._job:
            self._kernel32.CloseHandle(self._job)
            self._job = None


class SingleInstance:
    """Holds a named mutex so a second copy of the station can detect the first.

    Two stations would fight over the robot (the robot only obeys one), so a
    second launch brings the open window forward and exits instead.
    """

    def __init__(self) -> None:
        self._handle: Optional[int] = None
        self.already_running = False
        if not IS_WINDOWS:
            return
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_ID}")
        self.already_running = kernel32.GetLastError() == _ERROR_ALREADY_EXISTS

    def focus_existing_window(self, title: str) -> None:
        if not IS_WINDOWS:
            return
        import ctypes
        user32 = ctypes.windll.user32
        window = user32.FindWindowW(None, title)
        if window:
            user32.ShowWindow(window, _SW_RESTORE)
            user32.SetForegroundWindow(window)

    def release(self) -> None:
        if self._handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
