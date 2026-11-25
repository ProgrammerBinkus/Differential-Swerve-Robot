"""Hardware access: motors, encoders and the IMU, real or simulated."""

from __future__ import annotations

import logging
from typing import Any, Optional

from common.config import ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS, motor_channel
from robot.hardware.encoder import MT6701, AngleSensor, SimEncoder
from robot.hardware.errors import HardwareError
from robot.hardware.imu import Imu
from robot.hardware.motor import HBridgeChannel, MotorOutput, SimMotorOutput
from robot.hardware.sim import SimGyro, SimPlant

__all__ = ["Hardware", "HardwareError", "open_hardware"]

log = logging.getLogger(__name__)


class Hardware:
    """Every device the robot drives or reads.

    Motor outputs are keyed by H-bridge channel (``"HB2.A"``) and encoders by
    ID (``"E1"``). The module mapping in the config decides which of them each
    swerve module uses, so remapping never reopens a motor.
    """

    def __init__(self, outputs: dict[str, MotorOutput], encoders: dict[str, AngleSensor],
                 imu: Imu, plant: Optional[SimPlant] = None) -> None:
        self.outputs = outputs
        self.encoders = encoders
        self.imu = imu
        self._plant = plant

    @property
    def simulated(self) -> bool:
        return self._plant is not None

    @property
    def chassis_velocity(self) -> Optional[tuple[float, float]]:
        """The simulated chassis' (vx, vy) in m/s, robot frame. ``None`` on the real robot: it has no drive encoders."""
        if self._plant is None:
            return None
        return self._plant.chassis_vx_mps, self._plant.chassis_vy_mps

    def output_for_motor(self, config: dict[str, Any], motor_id: str) -> MotorOutput:
        return self.outputs[".".join(motor_channel(config, motor_id))]

    def reconfigure(self, config: dict[str, Any]) -> None:
        """Follow a config change: reopen encoders (and the IMU) whose I2C bus changed."""
        self.imu.set_invert(config["imu"]["invert_yaw"])
        if self._plant is not None:
            self._plant.configure(config)
            return
        if self.imu.status == "absent" or self.imu.bus_path != config["imu"]["bus"]:
            self.imu.close()
            self.imu = Imu.open(config["imu"])  # still missing is not an error: it reports "absent"
            log.info("IMU on %s: %s", config["imu"]["bus"], self.imu.status)
        for encoder_id in ENCODER_IDS:
            bus = config["encoders"][encoder_id]["bus"]
            current = self.encoders[encoder_id]
            if getattr(current, "bus_path", None) != bus:
                replacement = MT6701(bus)  # raises HardwareError before anything is closed
                current.close()
                self.encoders[encoder_id] = replacement
                log.info("%s moved to %s", encoder_id, bus)

    def apply_tuning(self, tuning: dict[str, Any]) -> None:
        """Hand the motor-shaping settings (reverse balance, soft-start ramp) to every channel."""
        ramp = tuning["motor_ramp"]
        for output in self.outputs.values():
            output.configure(tuning["reverse_scale"], ramp if ramp > 0 else None)

    def step(self, dt: float) -> None:
        """Advance the simulator, if there is one."""
        if self._plant is not None:
            self._plant.step(dt)

    def stop_all(self) -> None:
        for output in self.outputs.values():
            output.stop()

    def close(self) -> None:
        for output in self.outputs.values():
            output.close()
        for encoder in self.encoders.values():
            encoder.close()
        self.imu.close()


def open_hardware(config: dict[str, Any], simulate: bool) -> Hardware:
    """Open every motor channel and encoder named in ``config``."""
    if simulate:
        outputs = {f"{hb}.{ch}": SimMotorOutput(f"{hb}.{ch}") for hb in HBRIDGE_IDS for ch in HBRIDGE_CHANNELS}
        encoders = {encoder_id: SimEncoder() for encoder_id in ENCODER_IDS}
        plant = SimPlant(outputs, encoders)
        plant.configure(config)
        log.info("Using simulated hardware")
        return Hardware(outputs, encoders, Imu(SimGyro(plant), config["imu"]["invert_yaw"]), plant)

    opened: list[Any] = []
    try:
        outputs = {}
        for hb in HBRIDGE_IDS:
            for ch in HBRIDGE_CHANNELS:
                name = f"{hb}.{ch}"
                outputs[name] = HBridgeChannel.open(name, config["hbridges"][hb][ch], config["pwm_frequency_hz"])
                opened.append(outputs[name])
        encoders = {}
        for encoder_id in ENCODER_IDS:
            encoders[encoder_id] = MT6701(config["encoders"][encoder_id]["bus"])
            opened.append(encoders[encoder_id])
    except Exception:
        for device in reversed(opened):
            try:
                device.close()
            except Exception:
                pass
        raise
    imu = Imu.open(config["imu"])  # optional: without it the robot drives robot-relative
    log.info("Opened 8 motor channels, 4 encoders, IMU %s", imu.status)
    return Hardware(outputs, encoders, imu)
