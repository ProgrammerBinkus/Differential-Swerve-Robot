"""Robot configuration: schema, defaults and validation.

The robot owns the live configuration and stores it in ``robot_config.json``.
The driver station receives a copy over the control channel, edits the mapping
and tuning sections, and sends changes back. Both sides run
:func:`validate_config`, so a bad edit is caught before it reaches hardware.

Robot frame, used everywhere in this project: **+x is forward (the side away
from the Orange Pi), +y is left**, angles are counter-clockwise positive, and a
steering angle of 0 means the wheel points forward.

Hardware names follow wiring sheet E-01, with two changes for the new front:

* H-bridges are numbered HB1-HB4 (sheet labels HB-F, HB-R, HB-B, HB-L).
* Encoders are numbered E1-E4 after their I2C bus (I2C0-I2C3).

Motor labels M1-M8 are unchanged. Module positions (FL, FR, BL, BR) use the
new front, so the sheet's FL module is now BL, FR is now FL, BR is now FR and
BL is now BR.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

MODULE_NAMES = ("FL", "FR", "BL", "BR")  # order used for kinematics and telemetry
HBRIDGE_IDS = ("HB1", "HB2", "HB3", "HB4")
HBRIDGE_CHANNELS = ("A", "B")
MOTOR_IDS = tuple(f"M{n}" for n in range(1, 9))
ENCODER_IDS = ("E1", "E2", "E3", "E4")

ENCODER_COUNTS = 16384  # MT6701 reports a 14-bit angle per revolution

# What the driver station may change at runtime: for each section, the keys
# each entry may set. Offsets are written only by Swerve Set Zero on the robot,
# and the H-bridge pin wiring only in robot_config.json.
EDITABLE_SECTIONS = ("motors", "encoders", "modules", "imu", "tuning", "field_relative")
MAPPING_SECTIONS = ("motors", "encoders", "modules", "imu")
IMU_ADDRESSES = (0x68, 0x69)  # MPU-6050: 0x68 with AD0 low (the GY-521 default), 0x69 with AD0 high
_EDITABLE_IMU_KEYS = {"bus", "invert_yaw"}
_EDITABLE_ENTRY_KEYS = {
    "motors": {"hbridge", "channel"},
    "encoders": {"bus"},
    "modules": {"motor_a", "motor_b", "encoder", "invert_a", "invert_b", "invert_encoder"},
}


class ConfigError(ValueError):
    """Raised when a configuration or configuration update is rejected."""


@dataclass(frozen=True)
class TuningField:
    """One tunable parameter, with the range the UI and validation enforce."""

    key: str
    label: str
    minimum: float
    maximum: float
    default: float
    unit: str = ""
    resolution: float = 0.01
    help: str = ""


TUNING_FIELDS = (
    TuningField("steer_kp", "Steer kP", 0.0, 5.0, 0.8, "/rad", 0.01,
                "Steer output per radian of angle error. Tune this first."),
    TuningField("steer_ki", "Steer kI", 0.0, 2.0, 0.0, "/rad·s", 0.01,
                "Leave at 0 unless wheels settle short of their target."),
    TuningField("steer_kd", "Steer kD", 0.0, 0.5, 0.0, "s/rad", 0.001,
                "Damps overshoot. Add a little after kP is set."),
    TuningField("steer_limit", "Steer output limit", 0.05, 1.0, 0.5, "", 0.01,
                "Largest steer command. Also caps steering speed so encoder wraps are never missed."),
    TuningField("steer_coupling", "Steer-to-drive coupling", -0.5, 0.5, 0.0, "", 0.005,
                "Subtracts k x steer from drive if steering alone makes the wheel creep."),
    TuningField("max_speed_mps", "Max wheel speed", 0.1, 10.0, 1.0, "m/s", 0.01,
                "Measured wheel speed at 100% drive. Full stick maps to this."),
    TuningField("max_turn_dps", "Max turn rate", 30.0, 1440.0, 360.0, "°/s", 1.0,
                "Full turn stick spins the robot this fast, or as fast as the wheels allow if that is less."),
    TuningField("accel_limit", "Acceleration limit", 0.5, 20.0, 4.0, "/s", 0.1,
                "How fast commands may change, in full-scale per second."),
    TuningField("forward_start", "Forward power start", 0.0, 0.95, 0.0, "", 0.01,
                "Duty where a motor first moves forward. The smallest command starts here, skipping the dead zone."),
    TuningField("forward_max", "Forward power max", 0.05, 1.0, 1.0, "", 0.01,
                "Duty at full command forward. Set it below where the H-bridge cuts out (the motor hums)."),
    TuningField("reverse_start", "Reverse power start", 0.0, 0.95, 0.0, "", 0.01,
                "Duty where a motor first moves in reverse."),
    TuningField("reverse_max", "Reverse power max", 0.05, 1.0, 1.0, "", 0.01,
                "Duty at full command in reverse. The AT8236 pushes harder in reverse, so this is usually lower."),
    TuningField("motor_ramp", "Motor soft start", 0.0, 50.0, 5.0, "/s", 0.5,
                "How fast a motor's power may rise (full scale per second), so it spins up instead of tripping "
                "the H-bridge's 4.2 A cut-out. 0 turns it off."),
    TuningField("one_way_drive", "Roll one direction only", 0.0, 1.0, 0.0, "", 1.0,
                "1: each wheel only rolls with both motors in reverse (the AT8236's strong direction) and turns "
                "180° instead of rolling the other way. 0: normal. Needs both of a wheel's motors inverted alike."),
    TuningField("disable_brake_s", "Brake time after disable", 0.0, 15.0, 15.0, "s", 0.5,
                "After disabling, brake the motors this long, then let them coast. 15 s stops a fast robot; "
                "shorter suits H-bridges that misbehave while braking."),
    TuningField("hold_threshold", "Hold-angle threshold", 0.0, 0.2, 0.02, "", 0.005,
                "Below this speed fraction a wheel keeps its last angle instead of snapping to 0."),
    TuningField("home_tolerance_deg", "Return-to-zero tolerance", 0.5, 20.0, 3.0, "°", 0.1,
                "How close to zero counts as parked."),
)
TUNING_BY_KEY = {field.key: field for field in TUNING_FIELDS}


def _hbridge_channel(pwm_chip: int, pwm_channel: int, pwm_pin: int, pwm_function: str,
                     dir_name: str, dir_pin: int) -> dict[str, Any]:
    """One H-bridge input pair: hardware PWM on IN1, a direction GPIO on IN2.

    ``pwm.chip``/``pwm.channel`` index ``/sys/class/pwm/pwmchipN/pwmM``. The
    direction pin is found by its kernel line name (e.g. ``PD1``); add
    ``"chip": "/dev/gpiochipN", "line": K`` to the ``dir`` entry to pin it down
    explicitly. Run ``tools/probe_hardware.py`` on the Pi to confirm both.
    """
    return {
        "pwm": {"chip": pwm_chip, "channel": pwm_channel,
                "header_pin": pwm_pin, "function": pwm_function},
        "dir": {"name": dir_name, "header_pin": dir_pin},
    }


_DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    # Physical wiring of each H-bridge channel (wiring sheet E-02).
    # Edited in this file only, because changing it means rewiring the robot.
    # Where a PWM pin has a free GPIO right beside it, that GPIO is its channel's direction pin, so
    # the pair takes one 2-pin connector: 29+31, 38+40 and 7+8. The other PWM pins sit between PWM
    # and ground pins (header rows 15-20), so their channels need two separate 1-pin connectors.
    "hbridges": {
        "HB1": {"A": _hbridge_channel(0, 0, 29, "PWM0-0", "PD1", 31),       # paired
                "B": _hbridge_channel(0, 2, 33, "PWM0-2", "PD23", 22)},
        # HB2's direction wires are swapped from the original plan (one wire was too short to reach),
        # and channel A's moved again from header pin 15 (PK24), whose output stopped working, to pin 13.
        "HB2": {"A": _hbridge_channel(0, 3, 35, "PWM0-3", "PL12", 13),
                "B": _hbridge_channel(0, 4, 37, "PWM0-4", "PE12", 24)},
        "HB3": {"A": _hbridge_channel(0, 5, 32, "PWM0-5", "PK25", 18),
                "B": _hbridge_channel(0, 6, 36, "PWM0-6", "PL5", 16)},
        "HB4": {"A": _hbridge_channel(0, 7, 38, "PWM0-7", "PL13", 40),      # paired
                # S-PWM is the PWM block at 0x7023000, which the Orange Pi 1.0.8 image numbers pwmchip20.
                # PL6 doubles as UART7 TX, which stays off (no uart7 overlay).
                "B": _hbridge_channel(20, 2, 7, "S-PWM0-2", "PL6", 8)},     # paired
    },
    # Which H-bridge channel each motor is plugged into.
    "motors": {
        "M1": {"hbridge": "HB1", "channel": "A"},
        "M2": {"hbridge": "HB1", "channel": "B"},
        "M3": {"hbridge": "HB2", "channel": "A"},
        "M4": {"hbridge": "HB2", "channel": "B"},
        "M5": {"hbridge": "HB3", "channel": "A"},
        "M6": {"hbridge": "HB3", "channel": "B"},
        "M7": {"hbridge": "HB4", "channel": "A"},
        "M8": {"hbridge": "HB4", "channel": "B"},
    },
    # Which Linux I2C bus each encoder is on. `i2cdetect -l` shows the numbers.
    "encoders": {
        "E1": {"bus": "/dev/i2c-0", "label": "I2C0", "sda_pin": 3, "scl_pin": 5},
        "E2": {"bus": "/dev/i2c-1", "label": "I2C1", "sda_pin": 27, "scl_pin": 28},
        "E3": {"bus": "/dev/i2c-2", "label": "I2C2", "sda_pin": 19, "scl_pin": 23},
        "E4": {"bus": "/dev/i2c-3", "label": "I2C3", "sda_pin": 26, "scl_pin": 21},
    },
    # Which motors and encoder belong to each module. `offset` is the raw
    # encoder reading at zero steering angle, written by "Swerve Set Zero".
    "modules": {
        "FL": {"motor_a": "M2", "motor_b": "M3", "encoder": "E2",
               "invert_a": False, "invert_b": False, "invert_encoder": False, "offset": 0},
        "FR": {"motor_a": "M4", "motor_b": "M5", "encoder": "E3",
               "invert_a": False, "invert_b": False, "invert_encoder": False, "offset": 0},
        "BL": {"motor_a": "M1", "motor_b": "M8", "encoder": "E1",
               "invert_a": False, "invert_b": False, "invert_encoder": False, "offset": 0},
        "BR": {"motor_a": "M6", "motor_b": "M7", "encoder": "E4",
               "invert_a": False, "invert_b": False, "invert_encoder": False, "offset": 0},
    },
    # MPU-6050 (GY-521; this robot's is an MPU-6500) on I2C2 with encoder E3: spliced onto E3's run to
    # header pins 19/23. Turn the robot counter-clockwise by hand: the heading should go up. If it goes
    # down, the board is upside down: set invert_yaw.
    "imu": {"bus": "/dev/i2c-2", "address": 0x68, "invert_yaw": False, "sda_pin": 19, "scl_pin": 23},
    "tuning": {field.key: field.default for field in TUNING_FIELDS},
    # Per-motor power bands that override the Tuning tab's shared ones, measured on the stand when the
    # H-bridges make each motor's working range different: {"M1": {"forward": [start, max],
    # "reverse": [start, max]}}. Either direction may be left out. Edited in robot_config.json.
    "motor_bands": {},
    # Distance from the robot's center to each wheel's center along x and along y (110 mm, from the CAD).
    # It sets how fast the wheels must run for a given turn rate.
    "geometry": {"module_offset_m": 0.11},
    "loop_hz": 200,
    "pwm_frequency_hz": 20000,
    "watchdog_s": 0.25,
    # Drive relative to the field (forward = away from the driver station) using the MPU-6050 heading.
    "field_relative": False,
}


def default_config() -> dict[str, Any]:
    """A fresh copy of the default configuration."""
    return copy.deepcopy(_DEFAULT_CONFIG)


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Recursively copy ``source`` into ``target``, keeping keys ``source`` lacks."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def merge_config(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` with a remote ``update`` applied. ``base`` is not modified.

    Raises :class:`ConfigError` if the update touches a section that may not be
    changed remotely. The result still needs :func:`validate_config`.
    """
    forbidden = [key for key in update if key not in EDITABLE_SECTIONS]
    for section, allowed in _EDITABLE_ENTRY_KEYS.items():
        entries = update.get(section, {})
        if not isinstance(entries, dict):
            raise ConfigError(f"'{section}' must be an object")
        for entry_id, entry in entries.items():
            if not isinstance(entry, dict):
                raise ConfigError(f"'{section}.{entry_id}' must be an object")
            forbidden += [f"{section}.{entry_id}.{key}" for key in entry if key not in allowed]
    tuning = update.get("tuning", {})
    if not isinstance(tuning, dict):
        raise ConfigError("'tuning' must be an object")
    forbidden += [f"tuning.{key}" for key in tuning if key not in TUNING_BY_KEY]
    imu = update.get("imu", {})
    if not isinstance(imu, dict):
        raise ConfigError("'imu' must be an object")
    forbidden += [f"imu.{key}" for key in imu if key not in _EDITABLE_IMU_KEYS]
    if forbidden:
        raise ConfigError(f"These settings cannot be changed remotely: {', '.join(forbidden)}")
    result = copy.deepcopy(base)
    deep_update(result, update)
    return result


def motor_channel(config: dict[str, Any], motor_id: str) -> tuple[str, str]:
    """The (H-bridge, channel) pair a motor is plugged into."""
    entry = config["motors"][motor_id]
    return entry["hbridge"], entry["channel"]


def module_of_motor(config: dict[str, Any], motor_id: str) -> tuple[str, str] | None:
    """The (module, "a"/"b") slot a motor is assigned to, or ``None``."""
    for name, module in config["modules"].items():
        for slot in ("a", "b"):
            if module.get(f"motor_{slot}") == motor_id:
                return name, slot
    return None


def module_of_encoder(config: dict[str, Any], encoder_id: str) -> str | None:
    """The module an encoder is assigned to, or ``None``."""
    for name, module in config["modules"].items():
        if module.get("encoder") == encoder_id:
            return name
    return None


# --------------------------------------------------------------------------- validation

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _duplicates(items: list[Any]) -> list[Any]:
    seen, dupes = set(), []
    for item in items:
        if item in seen and item not in dupes:
            dupes.append(item)
        seen.add(item)
    return dupes


def _check_range(errors: list[str], name: str, value: Any, low: float, high: float) -> None:
    if not _is_number(value):
        errors.append(f"{name} must be a number")
    elif not low <= value <= high:
        errors.append(f"{name} must be between {low:g} and {high:g} (got {value:g})")


def _validate_hbridges(config: dict[str, Any], errors: list[str]) -> None:
    hbridges = config.get("hbridges")
    if not isinstance(hbridges, dict) or set(hbridges) != set(HBRIDGE_IDS):
        errors.append(f"hbridges must define exactly {', '.join(HBRIDGE_IDS)}")
        return
    pwm_outputs = []
    for hb_id in HBRIDGE_IDS:
        for channel in HBRIDGE_CHANNELS:
            spec = hbridges[hb_id].get(channel) if isinstance(hbridges[hb_id], dict) else None
            where = f"{hb_id} channel {channel}"
            if not isinstance(spec, dict):
                errors.append(f"{where} is missing")
                continue
            pwm, direction = spec.get("pwm"), spec.get("dir")
            if not (isinstance(pwm, dict) and _is_int(pwm.get("chip")) and _is_int(pwm.get("channel"))):
                errors.append(f"{where}: pwm needs integer 'chip' and 'channel'")
            else:
                pwm_outputs.append((pwm["chip"], pwm["channel"]))
            explicit = isinstance(direction, dict) and isinstance(direction.get("chip"), str) \
                and _is_int(direction.get("line"))
            named = isinstance(direction, dict) and isinstance(direction.get("name"), str)
            if not (explicit or named):
                errors.append(f"{where}: dir needs a line 'name' or a 'chip' path and 'line'")
    for chip, channel in _duplicates(pwm_outputs):
        errors.append(f"PWM chip {chip} channel {channel} is used by more than one H-bridge input")


def _validate_motors(config: dict[str, Any], errors: list[str]) -> None:
    motors = config.get("motors")
    if not isinstance(motors, dict) or set(motors) != set(MOTOR_IDS):
        errors.append(f"motors must define exactly {', '.join(MOTOR_IDS)}")
        return
    outputs = []
    for motor_id in MOTOR_IDS:
        entry = motors[motor_id]
        if not isinstance(entry, dict) or entry.get("hbridge") not in HBRIDGE_IDS \
                or entry.get("channel") not in HBRIDGE_CHANNELS:
            errors.append(f"{motor_id} needs an H-bridge ({'/'.join(HBRIDGE_IDS)}) and channel (A/B)")
            continue
        outputs.append((entry["hbridge"], entry["channel"]))
    for hb_id, channel in _duplicates(outputs):
        errors.append(f"{hb_id} channel {channel} is assigned to more than one motor")


def _validate_encoders(config: dict[str, Any], errors: list[str]) -> None:
    encoders = config.get("encoders")
    if not isinstance(encoders, dict) or set(encoders) != set(ENCODER_IDS):
        errors.append(f"encoders must define exactly {', '.join(ENCODER_IDS)}")
        return
    buses = []
    for encoder_id in ENCODER_IDS:
        bus = encoders[encoder_id].get("bus") if isinstance(encoders[encoder_id], dict) else None
        if not isinstance(bus, str) or not bus.strip():
            errors.append(f"{encoder_id} needs an I2C bus path such as /dev/i2c-0")
        else:
            buses.append(bus)
    for bus in _duplicates(buses):
        errors.append(f"I2C bus {bus} is assigned to more than one encoder "
                      "(every MT6701 answers at 0x06, so each needs its own bus)")


def _validate_modules(config: dict[str, Any], errors: list[str]) -> None:
    modules = config.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(MODULE_NAMES):
        errors.append(f"modules must define exactly {', '.join(MODULE_NAMES)}")
        return
    used_motors, used_encoders = [], []
    for name in MODULE_NAMES:
        module = modules[name]
        if not isinstance(module, dict):
            errors.append(f"module {name} is malformed")
            continue
        for slot in ("motor_a", "motor_b"):
            if module.get(slot) not in MOTOR_IDS:
                errors.append(f"module {name}: {slot} must be one of {', '.join(MOTOR_IDS)}")
            else:
                used_motors.append(module[slot])
        if module.get("encoder") not in ENCODER_IDS:
            errors.append(f"module {name}: encoder must be one of {', '.join(ENCODER_IDS)}")
        else:
            used_encoders.append(module["encoder"])
        for flag in ("invert_a", "invert_b", "invert_encoder"):
            if not isinstance(module.get(flag), bool):
                errors.append(f"module {name}: {flag} must be true or false")
        offset = module.get("offset")
        if not _is_int(offset) or not 0 <= offset < ENCODER_COUNTS:
            errors.append(f"module {name}: offset must be a whole number from 0 to {ENCODER_COUNTS - 1}")
    for motor_id in _duplicates(used_motors):
        errors.append(f"motor {motor_id} is assigned to more than one module slot")
    for encoder_id in _duplicates(used_encoders):
        errors.append(f"encoder {encoder_id} is assigned to more than one module")


def _validate_imu(config: dict[str, Any], errors: list[str]) -> None:
    imu = config.get("imu")
    if not isinstance(imu, dict):
        errors.append("imu section is missing")
        return
    if not isinstance(imu.get("bus"), str) or not imu["bus"].strip():
        errors.append("imu.bus must be an I2C bus path such as /dev/i2c-0")
    if imu.get("address") not in IMU_ADDRESSES:
        errors.append("imu.address must be 0x68 (104) or 0x69 (105)")
    if not isinstance(imu.get("invert_yaw"), bool):
        errors.append("imu.invert_yaw must be true or false")


def _validate_motor_bands(config: dict[str, Any], errors: list[str]) -> None:
    bands = config.get("motor_bands", {})
    if not isinstance(bands, dict):
        errors.append("motor_bands must be an object")
        return
    for motor_id, entry in bands.items():
        if motor_id not in MOTOR_IDS:
            errors.append(f"motor_bands: unknown motor {motor_id}")
            continue
        if not isinstance(entry, dict) or set(entry) - {"forward", "reverse"}:
            errors.append(f"motor_bands.{motor_id} may only hold 'forward' and 'reverse'")
            continue
        for direction, band in entry.items():
            ok = (isinstance(band, (list, tuple)) and len(band) == 2
                  and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in band)
                  and 0.0 <= band[0] < band[1] <= 1.0)
            if not ok:
                errors.append(f"motor_bands.{motor_id}.{direction} must be [start, max] with 0 <= start < max <= 1")


def motor_band(config: dict[str, Any], motor_id: str, direction: str) -> tuple[float, float]:
    """The (start, max) power band for one motor and direction: its own if set, else the shared one."""
    own = config.get("motor_bands", {}).get(motor_id, {}).get(direction)
    if own is not None:
        return float(own[0]), float(own[1])
    tuning = config["tuning"]
    return tuning[f"{direction}_start"], tuning[f"{direction}_max"]


def validate_config(config: dict[str, Any]) -> list[str]:
    """Check a full configuration. Returns a list of problems (empty if valid)."""
    errors: list[str] = []
    _validate_hbridges(config, errors)
    _validate_motors(config, errors)
    _validate_encoders(config, errors)
    _validate_modules(config, errors)
    _validate_imu(config, errors)

    tuning = config.get("tuning")
    if not isinstance(tuning, dict):
        errors.append("tuning section is missing")
    else:
        for field in TUNING_FIELDS:
            _check_range(errors, field.label, tuning.get(field.key), field.minimum, field.maximum)
        _validate_motor_bands(config, errors)
        for direction in ("forward", "reverse"):
            start, top = tuning.get(f"{direction}_start"), tuning.get(f"{direction}_max")
            if isinstance(start, (int, float)) and isinstance(top, (int, float)) and start >= top:
                errors.append(f"{direction.capitalize()} power start must be below {direction} power max")

    geometry = config.get("geometry")
    _check_range(errors, "geometry.module_offset_m",
                 geometry.get("module_offset_m") if isinstance(geometry, dict) else None, 0.02, 1.0)
    _check_range(errors, "loop_hz", config.get("loop_hz"), 50, 1000)
    _check_range(errors, "pwm_frequency_hz", config.get("pwm_frequency_hz"), 1000, 100000)
    _check_range(errors, "watchdog_s", config.get("watchdog_s"), 0.05, 2.0)
    if not isinstance(config.get("field_relative"), bool):
        errors.append("field_relative must be true or false")
    return errors
