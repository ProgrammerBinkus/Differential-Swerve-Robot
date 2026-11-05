"""The four-module drivetrain: chassis speeds in, motor commands out."""

from __future__ import annotations

import math
from typing import Any, Optional

from wpimath.geometry import Rotation2d, Translation2d
from wpimath.kinematics import ChassisSpeeds, SwerveDrive4Kinematics

from common.config import MODULE_NAMES
from robot.hardware import Hardware
from robot.swerve.mixing import steer_first_scale
from robot.swerve.module import DiffSwerveModule


class Drivetrain:
    """Runs the swerve pipeline for all four modules.

    Each loop, :meth:`drive` does:

    1. Scale the driver's fractions to real units (m/s and rad/s).
    2. Rotate to field-relative if a heading is supplied.
    3. ``toSwerveModuleStates``: chassis speeds -> one speed and angle per module.
    4. ``desaturateWheelSpeeds``: scale all four down together if any is over 100%.
    5. Per module: hold angle when stopped, optimize, cosine-scale, steer PID.
    6. Steer-first desaturation across all four, then the differential mix.
    """

    def __init__(self, modules: dict[str, DiffSwerveModule], config: dict[str, Any]) -> None:
        self.modules = [modules[name] for name in MODULE_NAMES]
        offset = config["geometry"]["module_offset_m"]
        positions = {"FL": (offset, offset), "FR": (offset, -offset),
                     "BL": (-offset, offset), "BR": (-offset, -offset)}
        self._kinematics = SwerveDrive4Kinematics(*(Translation2d(*positions[name]) for name in MODULE_NAMES))
        self._module_radius_m = math.hypot(offset, offset)
        self.apply_tuning(config["tuning"])

    @classmethod
    def from_config(cls, hardware: Hardware, config: dict[str, Any]) -> "Drivetrain":
        period_s = 1.0 / config["loop_hz"]
        modules = {}
        for name in MODULE_NAMES:
            module_config = config["modules"][name]
            modules[name] = DiffSwerveModule(
                name,
                hardware.output_for_motor(config, module_config["motor_a"]),
                hardware.output_for_motor(config, module_config["motor_b"]),
                hardware.encoders[module_config["encoder"]],
                module_config,
                config["tuning"],
                period_s,
            )
        return cls(modules, config)

    def apply_tuning(self, tuning: dict[str, float]) -> None:
        self.max_speed_mps = tuning["max_speed_mps"]
        # Full rotation stick spins the robot so each wheel runs at full speed.
        self.max_omega_rad_s = self.max_speed_mps / self._module_radius_m
        self._home_tolerance_rad = math.radians(tuning["home_tolerance_deg"])
        for module in self.modules:
            module.apply_tuning(tuning)

    def read_sensors(self) -> None:
        for module in self.modules:
            module.read_sensor()

    def drive(self, vx: float, vy: float, omega: float, heading_deg: Optional[float] = None) -> None:
        """Drive with fractions (-1 to 1) of top speed: +vx forward, +vy left, +omega counter-clockwise.

        Pass ``heading_deg`` (from the gyro) for field-relative driving.
        """
        speeds = ChassisSpeeds(vx * self.max_speed_mps, vy * self.max_speed_mps, omega * self.max_omega_rad_s)
        if heading_deg is not None:
            speeds = ChassisSpeeds.fromFieldRelativeSpeeds(
                speeds.vx, speeds.vy, speeds.omega, Rotation2d.fromDegrees(heading_deg))
        states = self._kinematics.toSwerveModuleStates(speeds)
        states = SwerveDrive4Kinematics.desaturateWheelSpeeds(states, self.max_speed_mps)
        plans = [module.plan(state, self.max_speed_mps) for module, state in zip(self.modules, states)]
        self._output(plans)

    def home(self) -> bool:
        """Steer every module to zero. Returns True once all working modules are there."""
        self._output([module.plan_home() for module in self.modules])
        return all(module.at_target(self._home_tolerance_rad) for module in self.modules if module.ready)

    def _output(self, plans: list[tuple[float, float]]) -> None:
        scale = steer_first_scale(plans)
        for module, (drive, steer) in zip(self.modules, plans):
            if module.ready:
                module.output(drive * scale, steer)
            else:
                module.stop()

    def stop(self) -> None:
        for module in self.modules:
            module.stop()

    def hold_current_angles(self) -> None:
        for module in self.modules:
            module.hold_current_angle()

    def rezero(self) -> dict[str, int]:
        """Make every module's current angle its zero. Returns the new offsets."""
        return {module.name: module.rezero() for module in self.modules if module.raw is not None}

    def telemetry(self) -> dict[str, dict[str, Any]]:
        return {module.name: module.telemetry() for module in self.modules}
