"""Whether each part is connected and working, from the robot's telemetry.

* The Orange Pi, encoders and IMU are known all the time: the robot reads them
  every loop.
* Motors and H-bridges have no feedback wire, so they are known only from the
  last motor check (each motor spun alone while its encoder watched). An
  H-bridge is judged from its two channels' motors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from common.config import ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS, MOTOR_IDS, module_of_encoder

OK, WARN, ERROR, UNKNOWN = "ok", "warn", "error", "unknown"
NOT_CHECKED = "Not checked yet. Enable with the wheels off the ground, then press Check motors."


@dataclass(frozen=True)
class PartStatus:
    level: str   # OK, WARN, ERROR or UNKNOWN
    text: str


def part_statuses(config: Optional[dict[str, Any]],
                  telemetry: Optional[dict[str, Any]]) -> dict[str, PartStatus]:
    """A status for the Pi, the IMU, every encoder, motor and H-bridge (``None`` telemetry: not connected)."""
    statuses: dict[str, PartStatus] = {}
    if telemetry is None:
        statuses["pi"] = PartStatus(ERROR, "Not connected")
        for part_id in ("mpu", *ENCODER_IDS, *MOTOR_IDS, *HBRIDGE_IDS):
            statuses[part_id] = PartStatus(UNKNOWN, "Robot not connected")
        return statuses

    statuses["pi"] = PartStatus(OK, f"Connected · loop {telemetry.get('loop_ms', 0):.2f} ms")
    statuses["mpu"] = _imu_status(telemetry.get("imu") or {}, config)
    modules = telemetry.get("modules") or {}
    for encoder_id in ENCODER_IDS:
        statuses[encoder_id] = _encoder_status(encoder_id, config, modules)
    check = telemetry.get("check") or {}
    results = check.get("results") or {}
    for motor_id in MOTOR_IDS:
        statuses[motor_id] = _motor_status(motor_id, results.get(motor_id), check)
    for hb_id in HBRIDGE_IDS:
        statuses[hb_id] = _hbridge_status(hb_id, config, results, check)
    return statuses


def _imu_status(imu: dict[str, Any], config: Optional[dict[str, Any]]) -> PartStatus:
    where = f" on {config['imu']['bus']}" if config else ""
    return {
        "ok": PartStatus(OK, f"Answering{where}"),
        "calibrating": PartStatus(WARN, "Calibrating: keep the robot still"),
        "absent": PartStatus(ERROR, f"Not found{where}: check its wires, 3.3 V and address"),
        "fault": PartStatus(ERROR, f"Stopped answering{where}"),
    }.get(imu.get("status"), PartStatus(UNKNOWN, "No IMU data"))


def _encoder_status(encoder_id: str, config: Optional[dict[str, Any]], modules: dict[str, Any]) -> PartStatus:
    if not config:
        return PartStatus(UNKNOWN, "Waiting for the robot's configuration")
    module_name = module_of_encoder(config, encoder_id)
    if module_name is None:
        return PartStatus(UNKNOWN, "Not assigned to a module, so the robot doesn't read it")
    live = modules.get(module_name)
    bus = config["encoders"][encoder_id]["bus"]
    if not live:
        return PartStatus(UNKNOWN, "No data")
    if live.get("fault") or live.get("raw") is None:
        return PartStatus(ERROR, f"Not answering on {bus}: check its SDA, SCL, 3.3 V and GND wires")
    return PartStatus(OK, f"Answering on {bus}")


def _motor_status(motor_id: str, result: Optional[dict[str, Any]], check: dict[str, Any]) -> PartStatus:
    if check.get("state") == "running" and check.get("current") == motor_id:
        return PartStatus(WARN, "Checking now…")
    if result is None:
        if check.get("state") == "running":
            return PartStatus(UNKNOWN, "Waiting its turn in the motor check")
        return PartStatus(UNKNOWN, NOT_CHECKED)
    if result.get("ok"):
        return PartStatus(OK, f"Spun: turned the {result.get('module')} module {result.get('moved', 0):+.0f}°")
    if result.get("ok") is False:
        return PartStatus(ERROR, f"Didn't turn the {result.get('module')} module: check this motor's leads "
                                 "and its H-bridge channel")
    note = str(result.get("note") or "not checked")
    return PartStatus(UNKNOWN, note[:1].upper() + note[1:])


def _hbridge_status(hb_id: str, config: Optional[dict[str, Any]], results: dict[str, Any],
                    check: dict[str, Any]) -> PartStatus:
    if not config:
        return PartStatus(UNKNOWN, "Waiting for the robot's configuration")
    channels: dict[str, Optional[str]] = {channel: None for channel in HBRIDGE_CHANNELS}
    for motor_id, entry in config["motors"].items():
        if entry.get("hbridge") == hb_id and entry.get("channel") in channels:
            channels[entry["channel"]] = motor_id
    outcome = {channel: (results.get(motor_id) or {}).get("ok") if motor_id else None
               for channel, motor_id in channels.items()}
    if check.get("state") == "running" and check.get("current") in channels.values():
        return PartStatus(WARN, "Checking now…")
    working = [c for c, ok in outcome.items() if ok]
    failed = [c for c, ok in outcome.items() if ok is False]
    if failed and not working and len(failed) == len(outcome):
        return PartStatus(ERROR, "Neither channel turned its motor: check this board's VM/GND power, "
                                 "its 3.3 V VCC and its control wires")
    if failed:
        dead = ", ".join(f"{c} ({channels[c]})" for c in failed)
        return PartStatus(WARN, f"Channel {dead} didn't turn its motor: check that motor's leads, "
                                "or the channel itself")
    if working and len(working) == len(outcome):
        return PartStatus(OK, "Both channels drive their motors")
    if working:
        return PartStatus(OK, f"Powered: channel {working[0]} drives its motor (the other wasn't checked)")
    return PartStatus(UNKNOWN, NOT_CHECKED)


def summary(statuses: dict[str, PartStatus]) -> tuple[str, str]:
    """One line for the Robot control card, and its level."""
    if statuses.get("pi", PartStatus(ERROR, "")).level == ERROR:
        return "Robot not connected", UNKNOWN
    encoders = sum(statuses[e].level == OK for e in ENCODER_IDS)
    motor_levels = [statuses[m].level for m in MOTOR_IDS]
    motors_ok, motors_bad = motor_levels.count(OK), motor_levels.count(ERROR)
    imu = statuses["mpu"].level
    parts = [f"Encoders {encoders}/{len(ENCODER_IDS)}", f"IMU {'ok' if imu == OK else 'missing' if imu == ERROR else '…'}"]
    if any(statuses[m].text == "Checking now…" for m in MOTOR_IDS):
        parts.append("checking motors…")
    elif motors_ok or motors_bad:
        bad = [m for m in MOTOR_IDS if statuses[m].level == ERROR]
        parts.append(f"Motors {motors_ok}/{len(MOTOR_IDS)}" + (f" ({', '.join(bad)} failed)" if bad else ""))
    else:
        parts.append("Motors not checked")
    worst = ERROR if (encoders < len(ENCODER_IDS) or motors_bad or imu == ERROR) else \
        OK if motors_ok == len(MOTOR_IDS) else WARN
    return "  ·  ".join(parts), worst
