"""One differential swerve module."""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from wpimath.controller import PIDController
from wpimath.geometry import Rotation2d
from wpimath.kinematics import SwerveModuleState

from robot.hardware.encoder import AngleSensor
from robot.hardware.motor import MotorOutput
from robot.swerve.mixing import clamp, mix
from robot.swerve.steering_angle import SteeringAngleTracker

log = logging.getLogger(__name__)


def _wrap(angle_rad: float) -> float:
    """Wrap an angle into [-pi, pi]."""
    return math.remainder(angle_rad, 2 * math.pi)


class DiffSwerveModule:
    """Two motors that share driving and steering, plus a steering encoder.

    Each loop the drivetrain calls :meth:`read_sensor`, then :meth:`plan` (or
    :meth:`plan_home`) to get a (drive, steer) pair, then :meth:`output` with
    the drive scaled by the steer-first desaturation.

    * Steering is closed-loop: a PID on the module angle from the encoder.
    * Driving is open-loop: there are no drive encoders, so drive is the
      wanted wheel speed divided by the measured top speed.

    A module whose encoder stops answering is marked faulted and coasts until
    readings come back, because steering without an angle would spin the
    wheel uncontrollably.
    """

    MAX_CONSECUTIVE_READ_ERRORS = 10  # 50 ms at 200 Hz

    def __init__(self, name: str, motor_a: MotorOutput, motor_b: MotorOutput, encoder: AngleSensor,
                 module_config: dict[str, Any], tuning: dict[str, float], period_s: float) -> None:
        self.name = name
        self._motor_a = motor_a
        self._motor_b = motor_b
        self._invert_a = module_config["invert_a"]
        self._invert_b = module_config["invert_b"]
        self._encoder = encoder
        self._tracker = SteeringAngleTracker(module_config["offset"], module_config["invert_encoder"])
        self._pid = PIDController(0.0, 0.0, 0.0, period_s)
        self._pid.enableContinuousInput(-math.pi, math.pi)
        self._target_rad: Optional[float] = None
        self._read_errors = 0

        self.raw: Optional[int] = None
        self.fault = False
        self.drive = 0.0
        self.steer = 0.0
        self.apply_tuning(tuning)

    # ----------------------------------------------------------------- state

    @property
    def ready(self) -> bool:
        """True once the angle is known and the encoder is answering."""
        return self._tracker.initialized and not self.fault

    @property
    def angle_rad(self) -> float:
        return self._tracker.angle_rad

    @property
    def target_rad(self) -> Optional[float]:
        return self._target_rad

    def apply_tuning(self, tuning: dict[str, float]) -> None:
        self._pid.setPID(tuning["steer_kp"], tuning["steer_ki"], tuning["steer_kd"])
        self._steer_limit = tuning["steer_limit"]
        self._coupling = tuning["steer_coupling"]
        self._hold_threshold = tuning["hold_threshold"]

    # --------------------------------------------------------------- sensing

    def read_sensor(self) -> None:
        try:
            raw = self._encoder.read_raw()
        except OSError as exc:
            self._read_errors += 1
            if self._read_errors >= self.MAX_CONSECUTIVE_READ_ERRORS and not self.fault:
                self.fault = True
                log.error("%s: encoder stopped answering (%s); module disabled", self.name, exc)
            return
        if self.fault:
            log.warning("%s: encoder answering again; check the wheel angle before driving", self.name)
            self.fault = False
        self._read_errors = 0
        self.raw = raw
        self._tracker.update(raw)
        if self._target_rad is None:
            self._target_rad = self._tracker.angle_rad

    # -------------------------------------------------------------- planning

    def plan(self, desired: SwerveModuleState, max_speed_mps: float) -> tuple[float, float]:
        """(drive, steer) toward a wanted state. ``desired`` is modified in place."""
        if not self.ready:
            return 0.0, 0.0
        current = Rotation2d(self.angle_rad)
        if abs(desired.speed) <= self._hold_threshold * max_speed_mps:
            # Nearly stopped: keep the last angle so the wheels do not snap back to 0.
            drive = 0.0
        else:
            desired.optimize(current)     # never turn more than 90 degrees; reverse instead
            desired.cosineScale(current)  # do not push while still turning toward the target
            self._target_rad = desired.angle.radians()
            drive = desired.speed / max_speed_mps
        steer = self._steer_toward(self._target_rad)
        return drive - self._coupling * steer, steer

    def plan_home(self) -> tuple[float, float]:
        """(drive, steer) toward the zero angle, with the wheel not rolling.

        The PID's continuous input treats every multiple of 360 degrees as
        zero, so the module takes the shortest way to a true zero (never the
        180-degree flip, which the encoder could not tell apart at start-up).
        """
        if not self.ready:
            return 0.0, 0.0
        self._target_rad = 0.0
        return 0.0, self._steer_toward(0.0)

    def at_target(self, tolerance_rad: float) -> bool:
        if self._target_rad is None:
            return False
        return abs(_wrap(self._target_rad - self.angle_rad)) <= tolerance_rad

    def _steer_toward(self, target_rad: float) -> float:
        return clamp(self._pid.calculate(self.angle_rad, target_rad), self._steer_limit)

    # ---------------------------------------------------------------- output

    def output(self, drive: float, steer: float) -> None:
        self.drive, self.steer = drive, steer
        a, b = mix(drive, steer)
        self._motor_a.set(-a if self._invert_a else a)
        self._motor_b.set(-b if self._invert_b else b)

    def stop(self) -> None:
        """Coast both motors and forget accumulated PID state."""
        self.drive = self.steer = 0.0
        self._motor_a.stop()
        self._motor_b.stop()
        self._pid.reset()

    def brake(self) -> None:
        """Brake both motors: the wheel slows down and the steering angle stays where it is."""
        self.drive = self.steer = 0.0
        self._motor_a.brake()
        self._motor_b.brake()
        self._pid.reset()

    def hold_current_angle(self) -> None:
        """Aim at wherever the wheel is now (used on enable, so nothing jumps)."""
        if self._tracker.initialized:
            self._target_rad = self.angle_rad
        self._pid.reset()

    def rezero(self) -> int:
        """Make the current position zero. Returns the new encoder offset."""
        offset = self._tracker.zero_here()
        self._target_rad = 0.0
        self._pid.reset()
        return offset

    def telemetry(self) -> dict[str, Any]:
        a, b = mix(self.drive, self.steer)
        return {
            "angle": round(math.degrees(_wrap(self.angle_rad)), 2) if self._tracker.initialized else None,
            "target": round(math.degrees(_wrap(self._target_rad)), 2) if self._target_rad is not None else None,
            "drive": round(self.drive, 4),
            "steer": round(self.steer, 4),
            "motors": [round(a, 4), round(b, 4)],
            "raw": self.raw,
            "offset": self._tracker.offset,
            "fault": self.fault,
        }
