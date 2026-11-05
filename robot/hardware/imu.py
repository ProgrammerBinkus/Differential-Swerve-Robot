"""MPU-6050 gyro and accelerometer (placeholder).

The BOM defers the IMU to later, so this class only reserves the interface the
rest of the code calls. When it is implemented (I2C0, address 0x68), ``update``
will integrate the Z-axis gyro rate into ``yaw_deg``, which turns on
field-relative driving and lets telemetry return MPU data to the laptop.
"""

from __future__ import annotations

from typing import Optional


class Mpu6050:
    def start(self) -> None:
        """Wake the sensor and calibrate the gyro bias (robot must be still)."""
        pass

    def update(self, dt: float) -> None:
        """Read the gyro and integrate the heading."""
        pass

    @property
    def yaw_deg(self) -> Optional[float]:
        """Heading in degrees, counter-clockwise positive, or ``None`` until implemented."""
        return None

    def reset_heading(self) -> None:
        pass

    def close(self) -> None:
        pass
