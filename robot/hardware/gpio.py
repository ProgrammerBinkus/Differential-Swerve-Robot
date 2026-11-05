"""Opening direction GPIOs by their kernel line name."""

from __future__ import annotations

import glob
from typing import Any

from robot.hardware.errors import HardwareError


def open_output(spec: dict[str, Any]):
    """Open a GPIO line as an output, initially low.

    ``spec`` is either ``{"chip": "/dev/gpiochipN", "line": K}`` or
    ``{"name": "PD1"}``. A name is looked up on every GPIO chip, because the
    Allwinner A733 splits its pins across more than one controller (the PL bank
    lives on a separate chip).
    """
    from periphery import GPIO, GPIOError

    if "chip" in spec and "line" in spec:
        try:
            return GPIO(spec["chip"], spec["line"], "low")
        except GPIOError as exc:
            raise HardwareError(f"Cannot open GPIO {spec['chip']} line {spec['line']}: {exc}") from exc

    name = spec["name"]
    last_error = "no /dev/gpiochip* devices found"
    for chip in sorted(glob.glob("/dev/gpiochip*")):
        try:
            return GPIO(chip, name, "low")
        except GPIOError as exc:
            last_error = str(exc)
    raise HardwareError(
        f"GPIO line {name!r} (header pin {spec.get('header_pin', '?')}) could not be opened: {last_error}. "
        "Run tools/probe_hardware.py, then set 'chip' and 'line' for it in robot_config.json."
    )
