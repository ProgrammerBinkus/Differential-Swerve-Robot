"""MPU-6050 gyro and accelerometer, and the robot's heading.

Wiring (sheet E-01): GY-521 board on I2C0 (header pins 3 SDA / 5 SCL),
address 0x68, sharing the bus with encoder E1, powered from 3.3 V.

The heading comes from integrating the Z-axis (vertical) gyro. The MPU-6050
has no magnetometer, so it measures turning, not compass direction: the
heading is relative to a reference the driver sets ("Set field forward"),
and drifts slowly (a few degrees a minute) until it is set again.

:class:`HeadingTracker` is the math (bias calibration, integration, the
field reference) and has no hardware in it. :class:`Imu` is what the robot
uses: it feeds a tracker from a real MPU-6050, the simulator, or nothing.
"""

from __future__ import annotations

import logging
import struct
from typing import Any, Optional, Protocol

from robot.hardware.errors import HardwareError

log = logging.getLogger(__name__)


def wrap_degrees(angle: float) -> float:
    """Wrap into [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


class HeadingTracker:
    """Turns gyro rate samples into a heading relative to the field.

    1. **Calibration.** For the first ``calibration_s`` the robot must be
       still. The average rate over that time is the gyro's bias (its reading
       at rest), subtracted from every later sample. If the rate swings more
       than ``still_dps`` from the first sample, the robot moved, and
       calibration starts again.
    2. **Integration.** Heading += (rate - bias) x dt, every loop.
    3. **Field reference.** :meth:`set_field_forward` says which way the robot
       faces right now, measured from "away from the driver station":
       0 = away, 90 = facing the driver's left, 180 = toward the driver,
       -90 = facing the driver's right. Counter-clockwise is positive.
    """

    def __init__(self, calibration_s: float = 1.5, still_dps: float = 2.0) -> None:
        self._calibration_s = calibration_s
        self._still_dps = still_dps
        self._calibration_time = 0.0
        self._calibration_sum = 0.0
        self._calibration_first: Optional[float] = None
        self._bias = 0.0
        self._ready = False
        self._yaw = 0.0          # integrated, unwrapped, since calibration finished
        self._reference = 0.0    # the integrated yaw at which the field heading is 0
        self._rate = 0.0

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def bias_dps(self) -> float:
        return self._bias

    @property
    def rate_dps(self) -> float:
        """The latest bias-corrected turning rate (counter-clockwise positive)."""
        return self._rate

    @property
    def heading_deg(self) -> Optional[float]:
        """Field heading in [-180, 180), or ``None`` until calibration finishes."""
        return wrap_degrees(self._yaw - self._reference) if self._ready else None

    def add_sample(self, rate_dps: float, dt: float) -> None:
        if not self._ready:
            self._calibrate(rate_dps, dt)
            return
        self._rate = rate_dps - self._bias
        self._yaw += self._rate * dt

    def set_field_forward(self, facing_deg: float = 0.0) -> None:
        """Declare that the robot now faces ``facing_deg`` from "away from the driver station"."""
        self._reference = self._yaw - facing_deg

    def recalibrate(self) -> None:
        self._ready = False
        self._calibration_time = self._calibration_sum = 0.0
        self._calibration_first = None

    def _calibrate(self, rate_dps: float, dt: float) -> None:
        if self._calibration_first is None:
            self._calibration_first = rate_dps
        elif abs(rate_dps - self._calibration_first) > self._still_dps:
            self.recalibrate()  # the robot moved: start over
            return
        self._calibration_time += dt
        self._calibration_sum += rate_dps * dt
        if self._calibration_time >= self._calibration_s:
            self._bias = self._calibration_sum / self._calibration_time
            self._ready = True
            self._yaw = self._reference = 0.0  # facing away from the driver until told otherwise
            log.info("Gyro calibrated (bias %.3f deg/s)", self._bias)


class GyroSource(Protocol):
    def read_rate_dps(self) -> float: ...        # Z-axis rate, counter-clockwise positive (board flat, chip up)
    def read_sample(self) -> dict[str, Any]: ...  # accel (g), gyro (deg/s), temperature (C)
    def close(self) -> None: ...


class Mpu6050:
    """The MPU-6050 itself, over I2C. Raises ``OSError`` if a read fails."""

    WHO_AM_I = 0x75
    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B     # 14 bytes: accel x, y, z, temperature, gyro x, y, z (big-endian, signed)
    GYRO_ZOUT_H = 0x47

    # +/-2000 deg/s, the widest range: the turn-rate limit goes up to 1440 deg/s and a gyro that
    # hits its limit silently loses heading. One count is 0.06 deg/s, below the chip's own noise.
    GYRO_LSB_PER_DPS = 16.4
    ACCEL_LSB_PER_G = 16384.0   # +/-2 g range
    # Chips sold as MPU-6050 boards also include MPU-6500/9250 clones with other IDs; all share these registers.
    KNOWN_IDS = {0x68: "MPU-6050", 0x70: "MPU-6500", 0x71: "MPU-9250", 0x73: "MPU-9255", 0x98: "clone"}

    def __init__(self, bus_path: str, address: int = 0x68) -> None:
        from periphery import I2C, I2CError

        self.bus_path = bus_path
        self._address = address
        self._message = I2C.Message
        try:
            self._i2c = I2C(bus_path)
        except I2CError as exc:
            raise HardwareError(f"Cannot open I2C bus {bus_path} for the MPU-6050: {exc}") from exc
        try:
            self._start()
        except OSError as exc:
            self._i2c.close()
            raise HardwareError(f"No MPU-6050 answering at 0x{address:02x} on {bus_path}: {exc}") from exc

    def _read(self, register: int, length: int) -> bytes:
        messages = [self._message([register]), self._message([0] * length, read=True)]
        self._i2c.transfer(self._address, messages)
        return bytes(messages[1].data)

    def _write(self, register: int, value: int) -> None:
        self._i2c.transfer(self._address, [self._message([register, value])])

    def _start(self) -> None:
        chip = self._read(self.WHO_AM_I, 1)[0]
        log.info("IMU WHO_AM_I = 0x%02x (%s)", chip, self.KNOWN_IDS.get(chip, "unknown, continuing"))
        self._write(self.PWR_MGMT_1, 0x01)    # wake up, clock from the X gyro (steadier than the internal one)
        self._write(self.CONFIG, 0x03)        # digital low-pass filter ~44 Hz: smooths vibration
        self._write(self.SMPLRT_DIV, 0x04)    # 1 kHz / (1 + 4) = 200 Hz, matching the control loop
        self._write(self.GYRO_CONFIG, 0x18)   # +/-2000 deg/s
        self._write(self.ACCEL_CONFIG, 0x00)  # +/-2 g

    def read_rate_dps(self) -> float:
        (raw,) = struct.unpack(">h", self._read(self.GYRO_ZOUT_H, 2))
        return raw / self.GYRO_LSB_PER_DPS

    def read_sample(self) -> dict[str, Any]:
        ax, ay, az, temp, gx, gy, gz = struct.unpack(">7h", self._read(self.ACCEL_XOUT_H, 14))
        g, dps = self.ACCEL_LSB_PER_G, self.GYRO_LSB_PER_DPS
        return {"accel": [round(ax / g, 3), round(ay / g, 3), round(az / g, 3)],
                "gyro": [round(gx / dps, 2), round(gy / dps, 2), round(gz / dps, 2)],
                "temp": round(temp / 340.0 + 36.53, 1)}

    def close(self) -> None:
        self._i2c.close()


class Imu:
    """The robot's view of the IMU: heading, rates, status and telemetry.

    Status is one of ``"absent"`` (no IMU found at start-up; the robot still
    drives robot-relative), ``"calibrating"``, ``"ok"`` or ``"fault"`` (reads
    keep failing). Only ``"ok"`` gives a heading.
    """

    MAX_CONSECUTIVE_READ_ERRORS = 10

    def __init__(self, source: Optional[GyroSource], invert_yaw: bool = False,
                 tracker: Optional[HeadingTracker] = None) -> None:
        self._source = source
        self._sign = -1.0 if invert_yaw else 1.0
        self._tracker = tracker or HeadingTracker()
        self._read_errors = 0
        self._fault = False

    @classmethod
    def open(cls, imu_config: dict[str, Any]) -> "Imu":
        """Open the MPU-6050 named in the config, or an ``"absent"`` IMU if it is not there."""
        try:
            source: Optional[GyroSource] = Mpu6050(imu_config["bus"], imu_config["address"])
        except HardwareError as exc:
            log.warning("%s. Field-relative drive is unavailable.", exc)
            source = None
        return cls(source, imu_config["invert_yaw"])

    @property
    def bus_path(self) -> Optional[str]:
        return getattr(self._source, "bus_path", None)

    @property
    def status(self) -> str:
        if self._source is None:
            return "absent"
        if self._fault:
            return "fault"
        return "ok" if self._tracker.ready else "calibrating"

    @property
    def heading_deg(self) -> Optional[float]:
        """Field heading (0 = facing away from the driver station), or ``None`` if not available."""
        return self._tracker.heading_deg if self.status == "ok" else None

    def set_invert(self, invert_yaw: bool) -> None:
        self._sign = -1.0 if invert_yaw else 1.0

    def update(self, dt: float) -> None:
        if self._source is None:
            return
        try:
            rate = self._source.read_rate_dps() * self._sign
        except OSError as exc:
            self._read_errors += 1
            if self._read_errors >= self.MAX_CONSECUTIVE_READ_ERRORS and not self._fault:
                self._fault = True
                log.error("IMU stopped answering (%s); field-relative drive is off until it recovers", exc)
            return
        if self._fault:
            log.warning("IMU answering again; recalibrating the gyro (keep the robot still)")
            self._fault = False
            self._tracker.recalibrate()  # the heading may have changed unseen while it was down
        self._read_errors = 0
        self._tracker.add_sample(rate, dt)

    def set_field_forward(self, facing_deg: float) -> bool:
        if self.status != "ok":
            return False
        self._tracker.set_field_forward(facing_deg)
        return True

    def telemetry(self) -> dict[str, Any]:
        data: dict[str, Any] = {"status": self.status, "heading": None, "rate": None}
        if self.status == "ok":
            data["heading"] = round(self._tracker.heading_deg, 2)
            data["rate"] = round(self._tracker.rate_dps, 2)
        if self._source is not None and not self._fault:
            try:
                data.update(self._source.read_sample())
            except OSError:
                pass  # counted by update(); telemetry just goes without this sample
        return data

    def close(self) -> None:
        if self._source is not None:
            self._source.close()

