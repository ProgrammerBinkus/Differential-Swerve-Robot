"""The real-hardware code paths, run against a fake ``periphery`` library.

These classes only run on the Orange Pi, so nothing else exercises them on a
laptop. The fake records every call, which lets the tests check what would be
written to the PWM, GPIO and I2C devices, and in what order.
"""

import sys
import types

import pytest

from common.config import ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS, default_config
from robot.hardware import open_hardware
from robot.hardware.encoder import MT6701
from robot.hardware.errors import HardwareError
from robot.hardware.gpio import open_output
from robot.hardware.imu import Mpu6050
from robot.hardware.motor import HBridgeChannel

POWER_AND_GROUND_PINS = {1, 2, 4, 6, 9, 14, 17, 20, 25, 30, 34, 39}


class FakeBoard:
    """What the fake library has been asked to do."""

    def __init__(self):
        self.log = []                     # (device, action, value) in call order
        self.pwms = {}                    # (chip, channel) -> FakePWM
        self.gpios = {}                   # line name -> FakeGPIO
        self.i2c_buses = []               # bus paths opened
        self.gpio_lines = {"/dev/gpiochip0": {"PD1", "PD23", "PE12", "PK24", "PK25"},
                           "/dev/gpiochip1": {"PL5", "PL12", "PL13"}}
        self.registers = {}               # (address, register) -> bytes the device answers with
        self.writes = []                  # (address, register, value) for single-register writes
        self.missing_addresses = set()


@pytest.fixture
def board(monkeypatch):
    state = FakeBoard()

    class PWMError(IOError):
        pass

    class GPIOError(IOError):
        pass

    class I2CError(IOError):
        pass

    class PWM:
        def __init__(self, chip, channel):
            self.key = (chip, channel)
            self.period_ns = 0
            self.enabled = False
            self.closed = False
            state.pwms[self.key] = self
            state.log.append((self.key, "open", None))

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name in ("frequency", "duty_cycle", "duty_cycle_ns"):
                state.log.append((self.key, name, value))

        def enable(self):
            self.enabled = True
            state.log.append((self.key, "enable", None))

        def disable(self):
            self.enabled = False

        def close(self):
            self.closed = True

    class GPIO:
        def __init__(self, chip, line, direction):
            if line not in state.gpio_lines.get(chip, ()):
                raise GPIOError(f"no line {line} on {chip}")
            self.chip, self.line, self.direction = chip, line, direction
            self.value = direction == "high"
            self.closed = False
            state.gpios[line] = self

        def write(self, value):
            self.value = value
            state.log.append((self.line, "write", value))

        def close(self):
            self.closed = True

    class I2C:
        class Message:
            def __init__(self, data, read=False):
                self.data, self.read = list(data), read

        def __init__(self, path):
            self.path = path
            state.i2c_buses.append(path)

        def transfer(self, address, messages):
            if address in state.missing_addresses:
                raise I2CError("no acknowledge")
            first = messages[0]
            if len(messages) == 1:                       # register write
                state.writes.append((address, first.data[0], first.data[1]))
                return
            answer = state.registers.get((address, first.data[0]), bytes(len(messages[1].data)))
            messages[1].data = list(answer)

        def close(self):
            pass

    fake = types.ModuleType("periphery")
    fake.PWM, fake.PWMError, fake.GPIO, fake.GPIOError, fake.I2C, fake.I2CError = \
        PWM, PWMError, GPIO, GPIOError, I2C, I2CError
    monkeypatch.setitem(sys.modules, "periphery", fake)
    monkeypatch.setattr("robot.hardware.gpio.glob.glob", lambda pattern: sorted(state.gpio_lines))
    return state


# ------------------------------------------------------------------- motor channels

def test_channel_opens_at_20_khz_with_the_motor_coasting(board):
    spec = default_config()["hbridges"]["HB1"]["A"]
    HBridgeChannel.open("HB1.A", spec, 20000)
    pwm = board.pwms[(0, 0)]
    assert (pwm.frequency, pwm.duty_cycle, pwm.enabled) == (20000, 0.0, True)
    actions = [action for device, action, _ in board.log if device == (0, 0)]
    assert actions.index("duty_cycle") < actions.index("enable")   # never enabled with a stale duty
    assert board.gpios["PD1"].direction == "low"                    # IN2 low + IN1 0% = coast


def test_a_missing_direction_pin_releases_the_pwm_channel(board):
    spec = {"pwm": {"chip": 0, "channel": 0}, "dir": {"name": "PZ9", "header_pin": 99}}
    with pytest.raises(HardwareError, match="PZ9"):
        HBridgeChannel.open("HB1.A", spec, 20000)
    pwm = board.pwms[(0, 0)]
    assert not pwm.enabled and pwm.closed


def test_direction_pins_are_found_on_whichever_gpio_chip_has_them(board):
    assert open_output({"name": "PL12"}).chip == "/dev/gpiochip1"   # the PL bank is on its own chip
    assert open_output({"chip": "/dev/gpiochip0", "line": "PD1"}).chip == "/dev/gpiochip0"


def test_reverse_writes_direction_before_the_inverted_duty(board):
    channel = HBridgeChannel.open("HB1.A", default_config()["hbridges"]["HB1"]["A"], 20000)
    del board.log[:]
    channel.set(-0.25)
    assert board.log == [("PD1", "write", True), ((0, 0), "duty_cycle", 0.75)]


# ------------------------------------------------------------------------- sensors

def test_mt6701_reads_the_14_bit_angle_from_registers_3_and_4(board):
    board.registers[(0x06, 0x03)] = bytes([0xAB, 0xCC])
    assert MT6701("/dev/i2c-1").read_raw() == (0xAB << 6) | (0xCC >> 2) == 10995
    board.registers[(0x06, 0x03)] = bytes([0xFF, 0xFC])
    assert MT6701("/dev/i2c-1").read_raw() == 16383                 # full scale


def test_mt6701_read_failure_is_an_oserror(board):
    encoder = MT6701("/dev/i2c-1")
    board.missing_addresses.add(0x06)
    with pytest.raises(OSError):                                    # what the module's fault counter catches
        encoder.read_raw()


def test_mpu6050_setup_and_gyro_scale(board):
    board.registers[(0x68, 0x75)] = bytes([0x68])
    imu = Mpu6050("/dev/i2c-0", 0x68)
    assert board.writes == [(0x68, 0x6B, 0x01),    # wake, clock from the X gyro
                            (0x68, 0x1A, 0x03),    # 44 Hz low-pass filter
                            (0x68, 0x19, 0x04),    # 200 Hz sample rate
                            (0x68, 0x1B, 0x18),    # gyro +/-2000 deg/s
                            (0x68, 0x1C, 0x00)]    # accel +/-2 g
    board.registers[(0x68, 0x47)] = (1640).to_bytes(2, "big", signed=True)
    assert imu.read_rate_dps() == pytest.approx(100.0)
    board.registers[(0x68, 0x47)] = (-23616).to_bytes(2, "big", signed=True)
    assert imu.read_rate_dps() == pytest.approx(-1440.0)            # the fastest turn the tuning allows


def test_mpu6050_missing_is_reported_not_raised_by_open_hardware(board):
    board.missing_addresses.add(0x68)
    hardware = open_hardware(default_config(), simulate=False)
    assert hardware.imu.status == "absent"                          # the robot still drives robot-relative


# ---------------------------------------------------------------- the whole robot

def test_open_hardware_opens_every_pin_in_the_wiring_table(board):
    config = default_config()
    hardware = open_hardware(config, simulate=False)
    assert set(hardware.outputs) == {f"{hb}.{ch}" for hb in HBRIDGE_IDS for ch in HBRIDGE_CHANNELS}
    assert set(board.pwms) == {(0, 0), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (1, 2)}
    assert set(board.gpios) == {"PD1", "PD23", "PE12", "PL13", "PK25", "PL5", "PK24", "PL12"}
    assert all(pwm.enabled and pwm.duty_cycle == 0.0 for pwm in board.pwms.values())
    assert not any(gpio.value for gpio in board.gpios.values())     # every motor coasting
    assert board.i2c_buses == [f"/dev/i2c-{n}" for n in range(4)] + ["/dev/i2c-0"]  # 4 encoders, then the IMU
    hardware.close()
    assert all(not pwm.enabled and pwm.closed for pwm in board.pwms.values())
    assert all(gpio.closed for gpio in board.gpios.values())


def test_a_failed_open_releases_everything_already_opened(board):
    board.gpio_lines["/dev/gpiochip1"].discard("PL12")              # the last channel, HB4.B, cannot open
    with pytest.raises(HardwareError, match="PL12"):
        open_hardware(default_config(), simulate=False)
    assert all(not pwm.enabled and pwm.closed for pwm in board.pwms.values())


def test_no_header_pin_is_used_twice_or_lands_on_a_power_pin():
    config = default_config()
    pins = []
    for hb in HBRIDGE_IDS:
        for channel in HBRIDGE_CHANNELS:
            spec = config["hbridges"][hb][channel]
            pins += [spec["pwm"]["header_pin"], spec["dir"]["header_pin"]]
    for encoder_id in ENCODER_IDS:
        pins += [config["encoders"][encoder_id]["sda_pin"], config["encoders"][encoder_id]["scl_pin"]]
    assert len(pins) == len(set(pins)) == 24
    assert not set(pins) & POWER_AND_GROUND_PINS
    assert all(1 <= pin <= 40 for pin in pins)
    imu, e1 = config["imu"], config["encoders"]["E1"]               # the IMU shares E1's bus on purpose
    assert (imu["bus"], imu["sda_pin"], imu["scl_pin"]) == (e1["bus"], e1["sda_pin"], e1["scl_pin"])
