"""Opening direction GPIOs by their kernel line name."""

from __future__ import annotations

import glob
import os
import re
from typing import Any, Optional

from robot.hardware.errors import HardwareError

_SUNXI_PIN = re.compile(r"^P([A-Z])(\d{1,2})$")


def sunxi_number(name: str) -> Optional[int]:
    """Allwinner's global GPIO number for a pin name: ``PA0`` is 0, each bank is 32 pins (``PD1`` is 97).

    The A733 puts banks A-K on one controller and L-M on another, numbered on from 352 (``PL0``),
    which matches this rule. ``None`` if ``name`` is not a pin name.
    """
    match = _SUNXI_PIN.match(name)
    if not match or int(match.group(2)) > 31:
        return None
    return (ord(match.group(1)) - ord("A")) * 32 + int(match.group(2))


def chip_and_line(number: int, sysfs: str = "/sys/class/gpio") -> Optional[tuple[str, int]]:
    """The ``/dev/gpiochipN`` and line offset that hold a global GPIO number, from the kernel's sysfs ranges."""
    try:
        names = sorted(n for n in os.listdir(sysfs) if n.startswith("gpiochip"))
    except OSError:
        return None
    for entry in (os.path.join(sysfs, n) for n in names):
        try:
            with open(os.path.join(entry, "base")) as f:
                base = int(f.read())
            with open(os.path.join(entry, "ngpio")) as f:
                count = int(f.read())
        except (OSError, ValueError):
            continue
        if base <= number < base + count:
            try:
                devices = sorted(n for n in os.listdir(os.path.join(entry, "device")) if n.startswith("gpiochip"))
            except OSError:
                devices = []
            if devices:
                return "/dev/" + devices[0], number - base
    return None


def open_output(spec: dict[str, Any]):
    """Open a GPIO line as an output, initially low.

    ``spec`` is either ``{"chip": "/dev/gpiochipN", "line": K}`` or
    ``{"name": "PD1"}``. A name is looked up on every GPIO chip, because the
    Allwinner A733 splits its pins across more than one controller (the PL bank
    lives on a separate chip). Images whose lines carry no names (the Orange Pi
    1.0.8 image) fall back to Allwinner's pin numbering.
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
        except (GPIOError, LookupError) as exc:  # periphery raises LookupError for an unknown name
            last_error = str(exc)
    number = sunxi_number(name)
    located = chip_and_line(number) if number is not None else None
    if located:
        try:
            return GPIO(located[0], located[1], "low")
        except GPIOError as exc:
            last_error = f"{located[0]} line {located[1]}: {exc}"
    raise HardwareError(
        f"GPIO line {name!r} (header pin {spec.get('header_pin', '?')}) could not be opened: {last_error}. "
        "Run tools/probe_hardware.py, then set 'chip' and 'line' for it in robot_config.json."
    )
