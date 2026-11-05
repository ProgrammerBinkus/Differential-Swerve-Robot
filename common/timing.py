"""Keeps Windows from slowing the control loops down.

Windows 11 throttles the timers of programs whose windows are covered or that
run in the background ("power throttling"), and its default timer tick is
15.6 ms. Either can delay a 50 Hz command loop past the robot's 250 ms
watchdog. Both the driver station and the simulator call
:func:`request_steady_timers` at start-up. Does nothing on other systems.
"""

from __future__ import annotations

import sys

_PROCESS_POWER_THROTTLING = 4                   # PROCESS_INFORMATION_CLASS value
_THROTTLE_EXECUTION_SPEED = 0x1
_THROTTLE_IGNORE_TIMER_RESOLUTION = 0x4


def request_steady_timers() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    class PowerThrottlingState(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        # Control the two kinds of throttling and turn both off (state 0).
        state = PowerThrottlingState(1, _THROTTLE_EXECUTION_SPEED | _THROTTLE_IGNORE_TIMER_RESOLUTION, 0)
        kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
                                       ctypes.byref(state), ctypes.sizeof(state))
    except (AttributeError, OSError):
        pass  # older Windows: nothing to turn off
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms timer resolution for the life of the process
    except (AttributeError, OSError):
        pass
