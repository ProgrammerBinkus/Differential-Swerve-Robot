"""MT6701 magnetic angle encoders on I2C."""

from __future__ import annotations

from typing import Protocol

from common.config import ENCODER_COUNTS
from robot.hardware.errors import HardwareError


class AngleSensor(Protocol):
    def read_raw(self) -> int: ...
    def close(self) -> None: ...


class MT6701:
    """Reads the 14-bit angle from an MT6701 over I2C.

    The angle sits in two registers: 0x03 holds bits 13-6 and the top six bits
    of 0x04 hold bits 5-0. One combined write-then-read transaction returns
    both, because the chip advances to the next register automatically.
    Raises ``OSError`` (periphery's ``I2CError``) if the read fails.
    """

    ADDRESS = 0x06
    ANGLE_REGISTER = 0x03

    def __init__(self, bus_path: str) -> None:
        from periphery import I2C, I2CError

        self.bus_path = bus_path
        self._message = I2C.Message
        try:
            self._i2c = I2C(bus_path)
        except I2CError as exc:
            raise HardwareError(f"Cannot open I2C bus {bus_path}: {exc}. Is the I2C overlay enabled?") from exc

    def read_raw(self) -> int:
        messages = [self._message([self.ANGLE_REGISTER]), self._message([0x00, 0x00], read=True)]
        self._i2c.transfer(self.ADDRESS, messages)
        high, low = messages[1].data
        return ((high << 6) | (low >> 2)) % ENCODER_COUNTS

    def close(self) -> None:
        self._i2c.close()


class SimEncoder:
    """An encoder whose reading is set by the simulator or a test."""

    def __init__(self, raw: int = 0) -> None:
        self.raw = raw
        self.fail = False  # tests set this to simulate a broken I2C link

    def read_raw(self) -> int:
        if self.fail:
            raise OSError("simulated I2C failure")
        return self.raw

    def close(self) -> None:
        pass
