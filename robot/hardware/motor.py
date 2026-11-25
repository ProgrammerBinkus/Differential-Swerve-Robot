"""AT8236 H-bridge channels (one per motor)."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from robot.hardware.errors import HardwareError
from robot.hardware.gpio import open_output

log = logging.getLogger(__name__)

DEADZONE = 0.02          # commands smaller than this are zero: a power band's start would otherwise jump them up
PERMISSION_WAIT_S = 2.0  # how long a new PWM channel may take to become writable


class MotorOutput(Protocol):
    name: str
    output: float  # last command, -1 to 1
    braking: bool

    def configure(self, forward_band: tuple[float, float], reverse_band: tuple[float, float],
                  ramp_per_s: float | None) -> None: ...
    def set(self, command: float) -> None: ...
    def stop(self) -> None: ...   # coast
    def brake(self) -> None: ...  # short the motor leads
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

    The two directions are not equally strong. Between pulses, forward lets
    the motor current die away (coast), while reverse keeps it flowing
    (brake), so the same duty pushes much harder in reverse. And a motor
    at rest draws its full stall current for the first few milliseconds,
    more than the AT8236's 4.2 A overcurrent trip, which then cuts out and
    retries every few ms: the motor hums and never starts. So, when
    :meth:`configure` turns them on:

    * a *power band* per direction maps a command's size (0 to 1) onto the
      duty range where that direction really works: from ``start`` (the duty
      where the motor first moves, so small commands are not lost in a dead
      zone) to ``max`` (just below where the H-bridge cuts out). Commands
      under 2% are treated as zero. The default band is the whole 0-1 range.
    * ``ramp_per_s`` lets the applied power *rise* only this fast (full scale
      per second), so the motor spins up before it can ask for a stall-sized
      surge. Lowering the power, braking and stopping are always immediate.
    """

    def __init__(self, name: str, pwm, direction) -> None:
        self.name = name
        self.output = 0.0
        self._pwm = pwm
        self._direction = direction
        self._reverse = False
        self._duty = 0.0
        self.braking = False
        self.forward_band = (0.0, 1.0)  # (start, max) duty for forward commands
        self.reverse_band = (0.0, 1.0)
        self.ramp_per_s = None        # None: no ramp, power changes at once
        self._applied = 0.0           # the command actually on the pins, after scaling and ramping
        self._last_set = None

    def configure(self, forward_band: tuple[float, float], reverse_band: tuple[float, float],
                  ramp_per_s: float | None) -> None:
        self.forward_band = forward_band
        self.reverse_band = reverse_band
        self.ramp_per_s = ramp_per_s

    def _map(self, command: float) -> float:
        """A command (-1 to 1) to the signed power actually sent, through the direction's band."""
        size = abs(command)
        if size < DEADZONE:
            return 0.0
        start, top = self.forward_band if command > 0.0 else self.reverse_band
        power = start + size * (top - start)
        return power if command > 0.0 else -power

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
            # A freshly exported channel's files belong to root until udev hands them to the gpio
            # group (/usr/local/sbin/robot-pwm-perms on the Pi), a few milliseconds later.
            deadline = time.monotonic() + PERMISSION_WAIT_S
            while True:
                try:
                    if pwm.period_ns > 0:
                        pwm.duty_cycle_ns = 0  # the kernel rejects a period shorter than the current duty
                    pwm.frequency = frequency_hz
                    if pwm.polarity != "normal":
                        # The Orange Pi 4 Pro's kernel exports channels "inversed": duty 0 would hold
                        # IN1 high (full speed) and brake would drive full reverse. Its driver only
                        # takes a polarity once a period is set and while the channel is off, and it
                        # rejects disabling a channel that is already off.
                        if pwm.enabled:
                            pwm.disable()
                        pwm.polarity = "normal"
                    pwm.duty_cycle = 0.0
                    pwm.enable()
                    break
                except PermissionError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            direction = open_output(spec["dir"])
        except Exception:
            try:
                if pwm.enabled:   # the Pi's driver rejects disabling an idle channel
                    pwm.disable()
            except Exception:
                pass              # keep the original error, which says what went wrong
            finally:
                pwm.close()
            raise
        return cls(name, pwm, direction)

    def set(self, command: float) -> None:
        command = _clamp_unit(command)
        target = self._map(command)
        now = time.monotonic()
        dt = 0.0 if self._last_set is None else min(now - self._last_set, 0.05)
        self._last_set = now
        applied = self._applied
        if target * applied < 0.0:
            applied = 0.0                      # changing direction: from zero, never straight across
        if self.ramp_per_s is None or abs(target) <= abs(applied):
            applied = target                   # less power (or no ramp): at once
        else:
            step = min(self.ramp_per_s * dt, abs(target) - abs(applied))
            applied += step if target > 0.0 else -step
        self._applied = applied
        self._write(applied)
        self.output = command
        self.braking = False

    def _write(self, command: float) -> None:
        reverse = command < 0.0
        duty = 1.0 + command if reverse else command
        if reverse != self._reverse:
            # DIR flips first and the matching duty follows a few microseconds later.
            self._direction.write(reverse)
            self._reverse = reverse
        if abs(duty - self._duty) > 1e-4:
            self._pwm.duty_cycle = duty
            self._duty = duty

    def stop(self) -> None:
        """Coast (both inputs low): the motor spins freely."""
        self.set(0.0)

    def brake(self) -> None:
        """Brake (both inputs high): the chip shorts the motor leads, so the motor resists turning.

        The stopping force grows with speed; at a standstill it only makes the
        wheel stiff to turn by hand.
        """
        if not self._reverse:
            self._direction.write(True)
            self._reverse = True
        if self._duty != 1.0:
            self._pwm.duty_cycle = 1.0
            self._duty = 1.0
        self.output = 0.0
        self.braking = True
        self._applied = 0.0

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
        self.braking = False

    def configure(self, forward_band: tuple[float, float], reverse_band: tuple[float, float],
                  ramp_per_s: float | None) -> None:
        pass  # the simulated motors are ideal: equally strong both ways, no overcurrent trip

    def set(self, command: float) -> None:
        self.output = _clamp_unit(command)
        self.braking = False

    def stop(self) -> None:
        self.output = 0.0
        self.braking = False

    def brake(self) -> None:
        self.output = 0.0
        self.braking = True

    def close(self) -> None:
        self.stop()
