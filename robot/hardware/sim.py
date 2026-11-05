"""Simulated module physics, so the full stack runs on a laptop with ``--sim``."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

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
    """Treats each module as an ideal differential.

    Steering rate follows (a - b) / 2 with a short lag, and the encoder reading
    is generated from the steering angle through the 2:1 gearing. The plant
    assumes the config's invert flags match the "physical" robot, so it checks
    the software, not the wiring. Modules start a random amount (within 40
    degrees) away from zero, as they would after being pushed around by hand.
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

    def configure(self, config: dict[str, Any]) -> None:
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
        for state, out_a, sign_a, out_b, sign_b, _, _ in self._wiring:
            steer = (out_a.output * sign_a - out_b.output * sign_b) / 2.0
            target_rate = steer * self.STEER_RATE_AT_FULL_RAD_S
            state.rate_rad_s += (target_rate - state.rate_rad_s) * blend
            state.angle_rad += state.rate_rad_s * dt
        self._write_encoders()

    def _write_encoders(self) -> None:
        for state, _, _, _, _, encoder, encoder_sign in self._wiring:
            counts = encoder_sign * state.angle_rad * ENCODER_TO_MODULE_RATIO / TAU * ENCODER_COUNTS
            encoder.raw = int(round(state.zero_raw + counts)) % ENCODER_COUNTS
