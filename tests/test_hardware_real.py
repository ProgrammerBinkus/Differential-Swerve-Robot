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
                           "/dev/gpiochip1": {"PL5", "PL6", "PL12", "PL13"}}
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
            object.__setattr__(self, "polarity", "inversed")   # how the Orange Pi 4 Pro's kernel exports a channel
            self.enabled = False
            self.closed = False
            state.pwms[self.key] = self
            state.log.append((self.key, "open", None))

        def __setattr__(self, name, value):
            if name == "polarity" and (getattr(self, "enabled", False) or "frequency" not in self.__dict__):
                raise IOError("Invalid argument: polarity needs a period and a disabled channel")
            object.__setattr__(self, name, value)
            if name in ("frequency", "duty_cycle", "duty_cycle_ns", "polarity"):
                state.log.append((self.key, name, value))

        def enable(self):
            self.enabled = True
            state.log.append((self.key, "enable", None))

        def disable(self):
            if not self.enabled:
                raise IOError("Invalid argument: the Orange Pi's driver rejects disabling an idle channel")
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


def test_channel_turns_off_the_kernels_inverted_polarity_before_enabling(board):
    """Inverted, duty 0 would hold IN1 high (full speed) and brake would drive full reverse."""
    HBridgeChannel.open("HB1.A", default_config()["hbridges"]["HB1"]["A"], 20000)
    pwm = board.pwms[(0, 0)]
    assert pwm.polarity == "normal"
    actions = [action for device, action, _ in board.log if device == (0, 0)]
    assert actions.index("polarity") < actions.index("enable")


def test_channel_waits_for_udev_to_make_a_new_pwm_writable(board, monkeypatch):
    import robot.hardware.motor as motor_module

    refusals = [2]

    def enable_after_two_refusals(self):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Permission denied", "/sys/class/pwm/pwmchip20/pwm2/enable")
        self.enabled = True

    monkeypatch.setattr(sys.modules["periphery"].PWM, "enable", enable_after_two_refusals)
    monkeypatch.setattr(motor_module.time, "sleep", lambda s: None)
    HBridgeChannel.open("HB4.B", default_config()["hbridges"]["HB4"]["B"], 20000)
    assert board.pwms[(20, 2)].enabled and refusals[0] == 0

    refusals[0] = 10 ** 6                                            # never writable: give up, release the channel
    monkeypatch.setattr(motor_module, "PERMISSION_WAIT_S", 0.0)
    with pytest.raises(PermissionError):
        HBridgeChannel.open("HB4.B", default_config()["hbridges"]["HB4"]["B"], 20000)
    assert board.pwms[(20, 2)].closed


def test_a_missing_direction_pin_releases_the_pwm_channel(board):
    spec = {"pwm": {"chip": 0, "channel": 0}, "dir": {"name": "PZ9", "header_pin": 99}}
    with pytest.raises(HardwareError, match="PZ9"):
        HBridgeChannel.open("HB1.A", spec, 20000)
    pwm = board.pwms[(0, 0)]
    assert not pwm.enabled and pwm.closed


def test_direction_pins_are_found_on_whichever_gpio_chip_has_them(board):
    assert open_output({"name": "PL12"}).chip == "/dev/gpiochip1"   # the PL bank is on its own chip
    assert open_output({"chip": "/dev/gpiochip0", "line": "PD1"}).chip == "/dev/gpiochip0"


def _fake_sysfs(tmp_path):
    """The Orange Pi 1.0.8 image's GPIO ranges: banks A-K from 0 on gpiochip0, L-M from 352 on gpiochip1."""
    for base, count, cdev in ((0, 352, "gpiochip0"), (352, 64, "gpiochip1")):
        entry = tmp_path / f"gpiochip{base}"
        (entry / "device" / cdev).mkdir(parents=True)
        (entry / "base").write_text(f"{base}\n")
        (entry / "ngpio").write_text(f"{count}\n")
    return str(tmp_path)


def test_unnamed_lines_fall_back_to_allwinner_numbering(board, tmp_path, monkeypatch):
    from robot.hardware import gpio as gpio_module

    assert gpio_module.sunxi_number("PD1") == 97 and gpio_module.sunxi_number("PL12") == 364
    assert gpio_module.sunxi_number("GPIO5") is None and gpio_module.sunxi_number("PA40") is None
    sysfs = _fake_sysfs(tmp_path)
    assert gpio_module.chip_and_line(97, sysfs) == ("/dev/gpiochip0", 97)
    assert gpio_module.chip_and_line(364, sysfs) == ("/dev/gpiochip1", 12)
    assert gpio_module.chip_and_line(500, sysfs) is None

    # An image with no line names: only numbers open.
    board.gpio_lines = {"/dev/gpiochip0": {97}, "/dev/gpiochip1": {12}}
    real = gpio_module.chip_and_line
    monkeypatch.setattr(gpio_module, "chip_and_line", lambda number: real(number, sysfs))
    pd1 = open_output({"name": "PD1"})
    assert (pd1.chip, pd1.line) == ("/dev/gpiochip0", 97)
    assert open_output({"name": "PL12"}).line == 12


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


def test_temperature_scale_follows_the_chip_family():
    imu = Mpu6050.__new__(Mpu6050)          # just the conversion, no bus
    imu.chip_id = 0x68
    assert imu.temperature_c(0) == pytest.approx(36.53)                # MPU-6050
    imu.chip_id = 0x70
    assert imu.temperature_c(0) == pytest.approx(21.0)                 # MPU-6500, as on this robot


def test_mpu6050_missing_is_reported_not_raised_by_open_hardware(board):
    board.missing_addresses.add(0x68)
    hardware = open_hardware(default_config(), simulate=False)
    assert hardware.imu.status == "absent"                          # the robot still drives robot-relative


# ---------------------------------------------------------------- the whole robot

def test_open_hardware_opens_every_pin_in_the_wiring_table(board):
    config = default_config()
    hardware = open_hardware(config, simulate=False)
    assert set(hardware.outputs) == {f"{hb}.{ch}" for hb in HBRIDGE_IDS for ch in HBRIDGE_CHANNELS}
    assert set(board.pwms) == {(0, 0), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (20, 2)}  # S-PWM is pwmchip20
    assert set(board.gpios) == {"PD1", "PD23", "PE12", "PL12", "PK25", "PL5", "PL13", "PL6"}
    assert all(pwm.enabled and pwm.duty_cycle == 0.0 for pwm in board.pwms.values())
    assert not any(gpio.value for gpio in board.gpios.values())     # every motor coasting
    assert board.i2c_buses == [f"/dev/i2c-{n}" for n in range(4)] + ["/dev/i2c-2"]  # 4 encoders, then the IMU
    hardware.close()
    assert all(not pwm.enabled and pwm.closed for pwm in board.pwms.values())
    assert all(gpio.closed for gpio in board.gpios.values())


def test_a_failed_open_releases_everything_already_opened(board):
    board.gpio_lines["/dev/gpiochip1"].discard("PL6")               # the last channel, HB4.B, cannot open
    with pytest.raises(HardwareError, match="PL6"):
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
    imu, e3 = config["imu"], config["encoders"]["E3"]               # the IMU shares E3's bus on purpose
    assert (imu["bus"], imu["sda_pin"], imu["scl_pin"]) == (e3["bus"], e3["sda_pin"], e3["scl_pin"])


# The Orange Pi 4 Pro's 40-pin header, from its user manual (v1.4): pin -> GPIO, and its PWM function.
HEADER_GPIO = {3: "PB3", 5: "PB2", 7: "PL4", 8: "PL6", 10: "PL7", 11: "PL9", 12: "PL8", 13: "PL12", 15: "PK24",
               16: "PL5", 18: "PK25", 19: "PE2", 21: "PE3", 22: "PD23", 23: "PE1", 24: "PE12", 26: "PE4",
               27: "PB5", 28: "PB4", 29: "PD0", 31: "PD1", 32: "PD5", 33: "PD2", 35: "PD3", 36: "PD6",
               37: "PD4", 38: "PD7", 40: "PL13"}
HEADER_PWM = {7: "S-PWM0-2", 29: "PWM0-0", 33: "PWM0-2", 35: "PWM0-3", 37: "PWM0-4", 32: "PWM0-5",
              36: "PWM0-6", 38: "PWM0-7"}


def _side_by_side(a, b):
    """True if two header pins take one 2-pin connector: across a row, or one above the other."""
    low, high = sorted((a, b))
    return (high - low == 1 and low % 2 == 1) or high - low == 2


def test_hbridge_pins_match_the_orange_pi_header():
    config = default_config()
    for hb in HBRIDGE_IDS:
        for channel in HBRIDGE_CHANNELS:
            pwm, direction = config["hbridges"][hb][channel]["pwm"], config["hbridges"][hb][channel]["dir"]
            assert HEADER_PWM[pwm["header_pin"]] == pwm["function"], (hb, channel)
            assert HEADER_GPIO[direction["header_pin"]] == direction["name"], (hb, channel)
            assert direction["header_pin"] not in HEADER_PWM                  # every PWM pin is needed as PWM
    for encoder in config["encoders"].values():
        assert {encoder["sda_pin"], encoder["scl_pin"]} <= set(HEADER_GPIO)


def test_every_pwm_pin_with_a_free_neighbor_has_its_direction_pin_beside_it():
    config = default_config()
    i2c = {pin for e in config["encoders"].values() for pin in (e["sda_pin"], e["scl_pin"])}
    free = set(HEADER_GPIO) - set(HEADER_PWM) - i2c                       # pins a direction line can use
    pairs = {(s["pwm"]["header_pin"], s["dir"]["header_pin"])
             for hb in config["hbridges"].values() for s in hb.values()}
    together = {pwm for pwm, direction in pairs if _side_by_side(pwm, direction)}
    assert together == {7, 29, 38}
    # No other PWM pin could have been paired: each has no free pin beside it, or only pin 31 (taken by 29).
    for pwm in set(HEADER_PWM) - together:
        assert {pin for pin in free if _side_by_side(pwm, pin)} <= {31}


def test_each_motor_channel_gets_its_own_power_bands(board):
    config = default_config()
    config["tuning"].update(forward_start=0.6, forward_max=0.78, reverse_start=0.15, reverse_max=0.4)
    config["motor_bands"] = {"M2": {"forward": [0.5, 0.7]}}
    hardware = open_hardware(config, simulate=False)
    hardware.apply_tuning(config)
    m2 = hardware.output_for_motor(config, "M2")
    m1 = hardware.output_for_motor(config, "M1")
    assert (m2.forward_band, m2.reverse_band) == ((0.5, 0.7), (0.15, 0.4))
    assert (m1.forward_band, m1.reverse_band) == ((0.6, 0.78), (0.15, 0.4))
    hardware.close()
