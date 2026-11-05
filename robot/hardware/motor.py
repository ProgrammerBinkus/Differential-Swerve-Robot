"""AT8236 H-bridge channels (one per motor)."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from robot.hardware.errors import HardwareError
from robot.hardware.gpio import open_output

log = logging.getLogger(__name__)


class MotorOutput(Protocol):
    name: str
    output: float  # last command, -1 to 1

    def set(self, command: float) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(1.0, value))


class HBridgeChannel:
    """One AT8236 channel: hardware PWM on IN1, a direction GPIO on IN2.

    AT8236 truth table::

        IN1 IN2
         1   0   forward
         0   1   reverse
         1   1   brake
         0   0   coast (the chip sleeps after ~1 ms)

    Forward (DIR low): PWM alternates forward and coast, so duty = power.
    Reverse (DIR high): PWM alternates brake and reverse. The motor is driven
    while PWM is *low*, so the duty is inverted: duty = 1 + command
    (command -0.3 gives duty 0.7, which is 30% reverse).
    """

    def __init__(self, name: str, pwm, direction) -> None:
        self.name = name
        self.output = 0.0
        self._pwm = pwm
        self._direction = direction
        self._reverse = False
        self._duty = 0.0

    @classmethod
    def open(cls, name: str, spec: dict[str, Any], frequency_hz: float) -> "HBridgeChannel":
        from periphery import PWM, PWMError

        pwm_spec = spec["pwm"]
        try:
            pwm = PWM(pwm_spec["chip"], pwm_spec["channel"])
        except PWMError as exc:
            raise HardwareError(
                f"{name}: cannot open pwmchip{pwm_spec['chip']}/pwm{pwm_spec['channel']} "
                f"(header pin {pwm_spec.get('header_pin', '?')}, {pwm_spec.get('function', '?')}). "
                f"Is the PWM overlay enabled? {exc}"
            ) from exc
        try:
            if pwm.period_ns > 0:
                pwm.duty_cycle_ns = 0  # the kernel rejects a period shorter than the current duty
            pwm.frequency = frequency_hz
            pwm.duty_cycle = 0.0
            pwm.enable()
            direction = open_output(spec["dir"])
        except Exception:
            try:
                pwm.disable()
            finally:
                pwm.close()
            raise
        return cls(name, pwm, direction)

    def set(self, command: float) -> None:
        command = _clamp_unit(command)
        reverse = command < 0.0
        duty = 1.0 + command if reverse else command
        if reverse != self._reverse:
            # DIR flips first and the matching duty follows a few microseconds later.
            self._direction.write(reverse)
            self._reverse = reverse
        if abs(duty - self._duty) > 1e-4:
            self._pwm.duty_cycle = duty
            self._duty = duty
        self.output = command

    def stop(self) -> None:
        """Coast (both inputs low)."""
        self.set(0.0)

    def close(self) -> None:
        """Stop, then release both pins. Never raises: it runs during shutdown."""
        for action in (self.stop, self._pwm.disable, self._pwm.close, self._direction.close):
            try:
                action()
            except Exception as exc:
                log.warning("%s: error while closing: %s", self.name, exc)


class SimMotorOutput:
    """Records commands instead of driving a motor (``--sim`` mode and tests)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.output = 0.0

    def set(self, command: float) -> None:
        self.output = _clamp_unit(command)

    def stop(self) -> None:
        self.output = 0.0

    def close(self) -> None:
        self.stop()
