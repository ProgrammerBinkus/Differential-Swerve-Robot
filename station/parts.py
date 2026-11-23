"""Every part on the chassis: where it sits in the top-down view and what it does.

Positions come from the wiring diagram (sheet E-01), rotated a quarter turn so
the Orange Pi is at the rear (bottom of the screen) and the front is at the
top. Coordinates are in a 1000 x 1000 box around the chassis, +y down.

The IMU is the exception: it has since moved from the left side (where sheet
E-01 shows it) to between HB2 and the power hub, and is wired onto E3's I2C run
(I2C2, header pins 19/23) instead of E1's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from common.config import (
    HBRIDGE_CHANNELS, MODULE_NAMES, module_of_encoder, module_of_motor, motor_channel,
)
from station.part_status import part_statuses

MODULE_CENTERS = {"FL": (190, 190), "FR": (810, 190), "BL": (190, 810), "BR": (810, 810)}
MODULE_POD_RADIUS = 152

# Sheet E-01 labels, for cross-referencing the wiring diagram.
SHEET_LABELS = {"HB1": "HB-F", "HB2": "HB-R", "HB3": "HB-B", "HB4": "HB-L",
                "E1": "ENC FL", "E2": "ENC FR", "E3": "ENC BR", "E4": "ENC BL"}


@dataclass(frozen=True)
class Part:
    id: str
    kind: str          # compute, imu, power, hbridge, motor, encoder
    label: str
    x: float           # center
    y: float
    w: float
    h: float
    title: str
    subtitle: str
    role: str = ""


def _hbridge(hb_id: str, x: float, y: float) -> Part:
    return Part(hb_id, "hbridge", hb_id, x, y, 60, 60, f"{hb_id} · AT8236 dual H-bridge",
                f"Wiring sheet label {SHEET_LABELS[hb_id]} · 6.5–40 V, 3.5 A per channel, 4.2 A trip",
                "VM/GND from its own power-hub pad pair at battery voltage; VCC from the Pi's 3.3 V.")


def _motor(motor_id: str, x: float, y: float, vertical: bool) -> Part:
    w, h = (64, 90) if vertical else (90, 64)
    return Part(motor_id, "motor", motor_id, x, y, w, h, f"{motor_id} · 280 brushed motor",
                "3–12 V, 0.38 A rated", "Shares driving and steering with the other motor in its module.")


def _encoder(encoder_id: str, x: float, y: float) -> Part:
    return Part(encoder_id, "encoder", encoder_id, x, y, 38, 38, f"{encoder_id} · MT6701 magnetic encoder",
                f"Wiring sheet label {SHEET_LABELS[encoder_id]} · I2C address 0x06",
                "Geared 2:1 from the 90T wheel gear to the 45T encoder gear: one encoder turn is "
                "180° of steering. Powered from 3.3 V only.")


PARTS: tuple[Part, ...] = (
    Part("pi", "compute", "Orange Pi 4 Pro", 505, 672, 170, 225, "Orange Pi 4 Pro",
         "4 GB · Allwinner A733 · Wi-Fi 6 · rear of the chassis",
         "Runs the robot code at 200 Hz. Receives drive commands from this laptop over Wi-Fi, "
         "drives 8 motors through 8 hardware PWM + 8 direction pins and reads 4 encoders on 4 I2C buses. "
         "Powered from the hub's 5 V through header pins 2/4 (5 V) and 6 (GND)."),
    Part("pdh", "power", "Power hub", 495, 330, 90, 90, "Matek Mini Power Hub",
         "9–26 V in · 4 × 20 A pad pairs · 5 V / 3 A regulator",
         "Each pad pair feeds one H-bridge at battery voltage; the 5 V regulator powers the Orange Pi. "
         "The 12 V output is unused (it needs a 4–6S battery)."),
    Part("battery", "power", "3S LiPo", 677, 502, 205, 95, "Ovonic 3S LiPo",
         "11.1 V · 2200 mAh · 35C · XT60",
         "12.6 V full, 11.1 V nominal. Stop driving near 9.9 V (3.3 V per cell)."),
    Part("xt60", "power", "XT60", 388, 500, 26, 48, "XT60 connector", "Battery lead",
         "Mates the battery's lead to the power hub's pigtail."),
    Part("switch", "power", "SW", 388, 414, 30, 44, "30 A rocker switch",
         "Between the battery and the power hub",
         "Cuts all power. Press Return to Zero (+) before switching off, so the wheels are parked at zero "
         "for the next start-up."),
    Part("mpu", "imu", "IMU", 500, 235, 56, 44, "MPU-6050 (GY-521)",
         "I2C2 · address 0x68 · between HB2 and the power hub",
         "Spliced onto encoder E3's I2C run (header pins 19/23). Its gyro gives the heading for field-relative drive; it has no "
         "compass, so set field forward from the Drive tab, and again if the heading drifts."),
    _hbridge("HB1", 160, 500), _hbridge("HB2", 500, 155),
    _hbridge("HB3", 845, 500), _hbridge("HB4", 500, 860),
    _motor("M1", 160, 595, True), _motor("M2", 160, 405, True),
    _motor("M3", 405, 155, False), _motor("M4", 595, 155, False),
    _motor("M5", 845, 405, True), _motor("M6", 845, 595, True),
    _motor("M7", 595, 860, False), _motor("M8", 405, 860, False),
    _encoder("E2", 330, 325), _encoder("E3", 680, 325),
    _encoder("E1", 330, 675), _encoder("E4", 680, 675),
)
PARTS_BY_ID = {part.id: part for part in PARTS}


@dataclass(frozen=True)
class Wire:
    """One harness from wiring sheet E-01, routed in the same rotated coordinates as the parts."""

    id: str
    layer: str                       # battery, 5v, control, motor, i2c
    ends: tuple[str, ...]            # parts it connects
    points: tuple[tuple[float, float], ...]
    branch: tuple[tuple[float, float], ...] = ()


WIRE_LAYERS = (  # (layer, label) in drawing order, signals under power
    ("i2c", "I2C sensors"),
    ("control", "Motor control"),
    ("motor", "Motor leads"),
    ("5v", "5 V to Pi"),
    ("battery", "Battery power"),
)

WIRES: tuple[Wire, ...] = (
    Wire("W1", "battery", ("battery", "xt60"), ((575, 500), (401, 500))),
    Wire("W2", "battery", ("xt60", "switch", "pdh"), ((388, 476), (388, 310), (450, 310))),
    Wire("W3", "battery", ("pdh", "HB1"), ((450, 295), (220, 295), (220, 488), (190, 488))),
    Wire("W4", "battery", ("pdh", "HB2"), ((460, 285), (460, 172), (470, 172))),  # left of the IMU
    Wire("W5", "battery", ("pdh", "HB3"), ((540, 295), (800, 295), (800, 488), (815, 488))),
    Wire("W6", "battery", ("pdh", "HB4"), ((450, 360), (365, 360), (365, 804), (486, 804), (486, 830))),
    Wire("W7", "5v", ("pdh", "pi"), ((520, 375), (520, 560))),
    Wire("W8", "control", ("pi", "HB1"), ((420, 600), (205, 600), (205, 512), (190, 512))),
    Wire("W9", "control", ("pi", "HB2"), ((552, 560), (552, 200), (540, 200), (540, 172), (530, 172))),  # right of it
    Wire("W10", "control", ("pi", "HB3"), ((590, 700), (795, 700), (795, 512), (815, 512))),
    Wire("W11", "control", ("pi", "HB4"), ((512, 785), (512, 830))),
    Wire("W12", "i2c", ("pi", "E1"), ((420, 760), (330, 760), (330, 694))),
    Wire("W13", "i2c", ("pi", "E2"), ((420, 570), (330, 570), (330, 344))),
    Wire("W14", "i2c", ("pi", "E3", "mpu"), ((563, 560), (563, 400), (680, 400), (680, 344)),
         branch=((563, 400), (563, 235), (528, 235))),  # spliced off E3's run (pins 19/23) to the IMU
    Wire("W15", "i2c", ("pi", "E4"), ((590, 640), (680, 640), (680, 656))),
    Wire("M1", "motor", ("HB1", "M1"), ((160, 530), (160, 550))),
    Wire("M2", "motor", ("HB1", "M2"), ((160, 470), (160, 450))),
    Wire("M3", "motor", ("HB2", "M3"), ((470, 155), (450, 155))),
    Wire("M4", "motor", ("HB2", "M4"), ((530, 155), (550, 155))),
    Wire("M5", "motor", ("HB3", "M5"), ((845, 470), (845, 450))),
    Wire("M6", "motor", ("HB3", "M6"), ((845, 530), (845, 550))),
    Wire("M7", "motor", ("HB4", "M7"), ((530, 860), (550, 860))),
    Wire("M8", "motor", ("HB4", "M8"), ((470, 860), (450, 860))),
)


@dataclass
class PartInfo:
    title: str
    subtitle: str
    lines: list[str]   # facts, one per line
    note: str = ""     # what the part does, shown as a paragraph above the facts
    kind: str = "part"  # "part" or "module"


def _pin_text(config: dict[str, Any], hb_id: str, channel: str) -> str:
    spec = config["hbridges"][hb_id][channel]
    return (f"PWM pin {spec['pwm'].get('header_pin', '?')} ({spec['pwm'].get('function', '?')}), "
            f"DIR pin {spec['dir'].get('header_pin', '?')} ({spec['dir'].get('name', 'line ' + str(spec['dir'].get('line')))})")


def _fmt(value: Optional[float], suffix: str = "", digits: int = 1) -> str:
    return "—" if value is None else f"{value:+.{digits}f}{suffix}"


def describe(part_id: str, config: Optional[dict[str, Any]],
             telemetry: Optional[dict[str, Any]]) -> PartInfo:
    """Information for the side panel, combining static facts with the live config and telemetry."""
    modules = (telemetry or {}).get("modules", {})
    statuses = part_statuses(config, telemetry)

    if part_id in MODULE_NAMES:
        lines = []
        if config:
            module = config["modules"][part_id]
            for slot in ("a", "b"):
                motor_id = module[f"motor_{slot}"]
                hb_id, channel = motor_channel(config, motor_id)
                inverted = " (inverted)" if module[f"invert_{slot}"] else ""
                lines.append(f"Motor {slot.upper()}: {motor_id} on {hb_id} channel {channel}{inverted}")
                lines.append(f"    {statuses[motor_id].text}")
            encoder_id = module["encoder"]
            lines.append(f"Encoder: {encoder_id} on {config['encoders'][encoder_id]['bus']}"
                         f"{' (inverted)' if module['invert_encoder'] else ''}")
        live = modules.get(part_id)
        if live:
            lines += [
                f"Angle: {_fmt(live['angle'], '°')}   target {_fmt(live['target'], '°')}",
                f"Drive: {_fmt(live['drive'] * 100, '%', 0)}   steer {_fmt(live['steer'] * 100, '%', 0)}",
                f"Motor commands: A {_fmt(live['motors'][0] * 100, '%', 0)}   B {_fmt(live['motors'][1] * 100, '%', 0)}",
                "ENCODER NOT ANSWERING - module disabled" if live["fault"] else "Encoder OK",
            ]
        else:
            lines.append("No telemetry from the robot.")
        return PartInfo(f"{part_id} swerve module", "Differential: two motors drive and steer together", lines,
                        kind="module")

    part = PARTS_BY_ID[part_id]
    lines: list[str] = []
    if config and part.kind == "hbridge":
        for channel in HBRIDGE_CHANNELS:
            motor_id = next((m for m in config["motors"] if motor_channel(config, m) == (part_id, channel)), None)
            where = ""
            if motor_id:
                slot = module_of_motor(config, motor_id)
                where = f" → {motor_id}" + (f" ({slot[0]} module)" if slot else " (unassigned)")
            lines.append(f"Channel {channel}{where}: {_pin_text(config, part_id, channel)}")
    elif config and part.kind == "motor":
        hb_id, channel = motor_channel(config, part_id)
        slot = module_of_motor(config, part_id)
        lines.append(f"Plugged into {hb_id} channel {channel}: {_pin_text(config, hb_id, channel)}")
        if slot:
            module_name, letter = slot
            lines.append(f"Module {module_name}, motor {letter.upper()}")
            live = modules.get(module_name)
            if live:
                lines.append(f"Command: {_fmt(live['motors'][0 if letter == 'a' else 1] * 100, '%', 0)}")
        else:
            lines.append("Not assigned to a module")
    elif config and part.kind == "encoder":
        bus = config["encoders"][part_id]
        lines.append(f"Bus {bus['bus']} ({bus.get('label', '')}, header pins "
                     f"{bus.get('sda_pin', '?')} SDA / {bus.get('scl_pin', '?')} SCL)")
        module_name = module_of_encoder(config, part_id)
        if module_name:
            lines.append(f"Module {module_name}")
            live = modules.get(module_name)
            if live:
                lines.append(f"Raw reading {live['raw']} · zero offset {live['offset']}")
        else:
            lines.append("Not assigned to a module")
    elif part.kind == "compute" and telemetry:
        lines.append(f"Mode: {telemetry['mode']} · loop {telemetry['loop_ms']:.2f} ms "
                     f"(worst {telemetry['loop_ms_max']:.2f} ms)"
                     f"{' · SIMULATED HARDWARE' if telemetry.get('simulated') else ''}")
    elif part.kind == "imu":
        if config:
            imu = config["imu"]
            lines.append(f"Bus {imu['bus']} · address 0x{imu['address']:02x}"
                         f"{' · heading inverted' if imu['invert_yaw'] else ''}")
        data = (telemetry or {}).get("imu")
        if data:
            if data.get("heading") is not None:
                lines.append(f"Field heading {data['heading']:+.1f}° · turning {data['rate']:+.1f}°/s")
            if "accel" in data:
                ax, ay, az = data["accel"]
                lines.append(f"Accel {ax:+.2f} {ay:+.2f} {az:+.2f} g · {data.get('temp', 0):.1f} °C")
        else:
            lines.append("No telemetry from the robot.")
    status = statuses.get(part_id)
    if status is not None:
        lines.insert(0, f"Status: {status.text}")
    return PartInfo(part.title, part.subtitle, lines, part.role)
