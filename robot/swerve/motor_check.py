"""Motor check: spin each motor on its own and see whether its module's steering moves.

The robot has no current sensing, so the only proof that a motor, its leads and
its H-bridge channel work is the encoder seeing the module turn. With one motor
driven and its partner braked, a differential module steers at half the motor's
speed (steer = (a - b) / 2), so a working motor turns the wheel by tens of
degrees in a fraction of a second. A motor that doesn't move it is reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from common.config import MODULE_NAMES

from robot.swerve.drivetrain import Drivetrain


@dataclass
class MotorResult:
    ok: Optional[bool]        # None: not checked
    moved_deg: Optional[float]
    module: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "moved": None if self.moved_deg is None else round(self.moved_deg, 1),
                "module": self.module, "note": self.note}


class MotorCheck:
    """Steps through every motor of every module with a working encoder, one at a time.

    For each motor: brake its module and let it settle, drive the motor alone
    for ``PULSE_S`` with its partner braked, brake again, and compare the
    steering angle before and after. Every other module stays braked.
    """

    POWER = 0.35
    SETTLE_S = 0.3
    PULSE_S = 0.4
    MIN_MOVE_DEG = 3.0

    def __init__(self, drivetrain: Drivetrain, config: dict[str, Any], now: float) -> None:
        self._modules = {module.name: module for module in drivetrain.modules}
        self._steps: list[tuple[str, str, str]] = []   # (module, slot, motor id)
        self.results: dict[str, MotorResult] = {}
        for name in MODULE_NAMES:
            module_config = config["modules"][name]
            for slot in ("a", "b"):
                motor_id = module_config[f"motor_{slot}"]
                if self._modules[name].ready:
                    self._steps.append((name, slot, motor_id))
                else:
                    self.results[motor_id] = MotorResult(
                        None, None, name, f"not checked: encoder {module_config['encoder']} not answering")
        self.state = "running" if self._steps else "done"
        self._index = 0
        self._phase = "settle"
        self._phase_start = now
        self._start_angle = 0.0

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def current(self) -> Optional[str]:
        return self._steps[self._index][2] if self.running else None

    def step(self, now: float) -> bool:
        """Advance one control-loop tick. Returns True once the check has finished."""
        if not self.running:
            return True
        name, slot, motor_id = self._steps[self._index]
        module = self._modules[name]
        for other in self._modules.values():
            if other is not module:
                other.brake()
        if not module.ready:
            self.results[motor_id] = MotorResult(None, None, name, "not checked: encoder stopped answering")
            self._next(now)
            return not self.running

        elapsed = now - self._phase_start
        if self._phase == "settle":
            module.brake()
            if elapsed >= self.SETTLE_S:
                self._start_angle = module.angle_rad
                self._phase, self._phase_start = "pulse", now
        elif self._phase == "pulse":
            if elapsed >= self.PULSE_S:
                module.brake()
                self._phase, self._phase_start = "rest", now
            else:
                module.run_one_motor(slot, self.POWER)
        else:
            module.brake()
            if elapsed >= self.SETTLE_S:
                moved = math.degrees(module.angle_rad - self._start_angle)
                self.results[motor_id] = MotorResult(abs(moved) >= self.MIN_MOVE_DEG, moved, name)
                self._next(now)
        return not self.running

    def _next(self, now: float) -> None:
        self._index += 1
        self._phase, self._phase_start = "settle", now
        if self._index >= len(self._steps):
            self.state = "done"

    def abort(self, reason: str) -> None:
        """Stop where it is; every motor not yet measured is reported as not checked."""
        if not self.running:
            return
        for name, _slot, motor_id in self._steps[self._index:]:
            self.results[motor_id] = MotorResult(None, None, name, f"not checked: {reason}")
        self.state = "aborted"

    def summary(self) -> str:
        parts = []
        for motor_id in sorted(self.results):
            result = self.results[motor_id]
            if result.ok:
                parts.append(f"{motor_id} ok ({result.moved_deg:+.0f}°)")
            elif result.ok is False:
                parts.append(f"{motor_id} DID NOT MOVE its module")
            else:
                parts.append(f"{motor_id} {result.note}")
        return ", ".join(parts)

    def telemetry(self) -> dict[str, Any]:
        return {"state": self.state, "current": self.current,
                "results": {motor_id: result.to_dict() for motor_id, result in self.results.items()}}
