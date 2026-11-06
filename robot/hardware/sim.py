"""Simulated module physics, so the full stack runs on a laptop with ``--sim``."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from wpimath.geometry import Rotation2d, Translation2d
from wpimath.kinematics import SwerveDrive4Kinematics, SwerveModuleState

from common.config import ENCODER_COUNTS, MODULE_NAMES, motor_channel
from robot.constants import ENCODER_TO_MODULE_RATIO, TAU
from robot.hardware.encoder import SimEncoder
from robot.hardware.motor import SimMotorOutput


@dataclass
class _ModuleState:
    angle_rad: float
    zero_raw: int
    rate_rad_s: float = 0.0


class SimPlant:
    """Treats each module as an ideal differential, and the chassis as turning freely.

    Steering rate follows (a - b) / 2 with a short lag, and the encoder reading
    is generated from the steering angle through the 2:1 gearing. Each wheel
    rolls at (a + b) / 2 of the configured top speed in the direction it
    points; forward kinematics turns the four wheel velocities into the
    chassis' turning rate, which :class:`SimGyro` reports like an MPU-6050.

    The plant assumes the config's invert flags match the "physical" robot, so
    it checks the software, not the wiring. Modules start a random amount
    (within 40 degrees) away from zero, as they would after being pushed
    around by hand.
    """

    STEER_RATE_AT_FULL_RAD_S = TAU * 3.0
    RESPONSE_TIME_S = 0.06

    def __init__(self, outputs: dict[str, SimMotorOutput], encoders: dict[str, SimEncoder],
                 seed: int = 1) -> None:
        self._outputs = outputs
        self._encoders = encoders
        self._rng = random.Random(seed)
        self._states: dict[str, _ModuleState] = {}
        self._wiring: list[tuple[_ModuleState, SimMotorOutput, float, SimMotorOutput, float, SimEncoder, float]] = []
        self._kinematics: SwerveDrive4Kinematics | None = None
        self._max_speed_mps = 1.0
        self.chassis_rate_rad_s = 0.0   # counter-clockwise
        self.chassis_heading_rad = 0.0
        self.chassis_vx_mps = 0.0       # robot frame: +x forward, +y left
        self.chassis_vy_mps = 0.0

    def configure(self, config: dict[str, Any]) -> None:
        offset = config["geometry"]["module_offset_m"]
        positions = {"FL": (offset, offset), "FR": (offset, -offset), "BL": (-offset, offset), "BR": (-offset, -offset)}
        self._kinematics = SwerveDrive4Kinematics(*(Translation2d(*positions[name]) for name in MODULE_NAMES))
        self._max_speed_mps = config["tuning"]["max_speed_mps"]
        self._wiring = []
        for name in MODULE_NAMES:
            module = config["modules"][name]
            if name not in self._states:
                self._states[name] = _ModuleState(
                    angle_rad=math.radians(self._rng.uniform(-40.0, 40.0)), zero_raw=module["offset"])
            out_a = self._outputs[".".join(motor_channel(config, module["motor_a"]))]
            out_b = self._outputs[".".join(motor_channel(config, module["motor_b"]))]
            self._wiring.append((
                self._states[name],
                out_a, -1.0 if module["invert_a"] else 1.0,
                out_b, -1.0 if module["invert_b"] else 1.0,
                self._encoders[module["encoder"]], -1.0 if module["invert_encoder"] else 1.0,
            ))
        self._write_encoders()

    def step(self, dt: float) -> None:
        blend = min(1.0, dt / self.RESPONSE_TIME_S)
        wheels = []
        for state, out_a, sign_a, out_b, sign_b, _, _ in self._wiring:
            a, b = out_a.output * sign_a, out_b.output * sign_b
            target_rate = (a - b) / 2.0 * self.STEER_RATE_AT_FULL_RAD_S
            state.rate_rad_s += (target_rate - state.rate_rad_s) * blend
            state.angle_rad += state.rate_rad_s * dt
            wheels.append(SwerveModuleState((a + b) / 2.0 * self._max_speed_mps, Rotation2d(state.angle_rad)))
        if self._kinematics is not None and len(wheels) == len(MODULE_NAMES):
            speeds = self._kinematics.toChassisSpeeds(tuple(wheels))
            self.chassis_vx_mps, self.chassis_vy_mps = speeds.vx, speeds.vy
            self.chassis_rate_rad_s = speeds.omega
            self.chassis_heading_rad += self.chassis_rate_rad_s * dt
        self._write_encoders()

    def _write_encoders(self) -> None:
        for state, _, _, _, _, encoder, encoder_sign in self._wiring:
            counts = encoder_sign * state.angle_rad * ENCODER_TO_MODULE_RATIO / TAU * ENCODER_COUNTS
            encoder.raw = int(round(state.zero_raw + counts)) % ENCODER_COUNTS


class SimGyro:
    """Reports the simulated chassis' turning like an MPU-6050 lying flat (no bias, no noise)."""

    bus_path = "sim"

    def __init__(self, plant: SimPlant) -> None:
        self._plant = plant

    def read_rate_dps(self) -> float:
        return math.degrees(self._plant.chassis_rate_rad_s)

    def read_sample(self) -> dict[str, Any]:
        rate = round(self.read_rate_dps(), 2)
        return {"accel": [0.0, 0.0, 1.0], "gyro": [0.0, 0.0, rate], "temp": 30.0}

    def close(self) -> None:
        pass
