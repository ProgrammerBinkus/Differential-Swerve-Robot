"""Part statuses on the driver station: encoders and IMU live, motors and H-bridges from the motor check."""

from common.config import default_config
from station.part_status import ERROR, OK, UNKNOWN, WARN, part_statuses, summary


def _telemetry(faulted=(), imu="ok", results=None, state="done", current=None):
    modules = {name: {"fault": name in faulted, "raw": None if name in faulted else 1000}
               for name in ("FL", "FR", "BL", "BR")}
    check = None if results is None else {"state": state, "current": current, "results": results}
    return {"loop_ms": 1.2, "modules": modules, "imu": {"status": imu}, "check": check}


def _ok(module, moved=20.0):
    return {"ok": True, "moved": moved, "module": module, "note": ""}


def _dead(module):
    return {"ok": False, "moved": 0.4, "module": module, "note": ""}


def test_not_connected():
    statuses = part_statuses(default_config(), None)
    assert statuses["pi"].level == ERROR
    assert {statuses[p].level for p in ("E1", "M1", "HB1", "mpu")} == {UNKNOWN}
    assert summary(statuses)[0] == "Robot not connected"


def test_encoders_follow_their_modules_and_motors_start_unchecked():
    config = default_config()
    statuses = part_statuses(config, _telemetry(faulted=("FL",)))
    fl_encoder = config["modules"]["FL"]["encoder"]
    assert statuses[fl_encoder].level == ERROR
    assert all(statuses[e].level == OK for e in ("E1", "E2", "E3", "E4") if e != fl_encoder)
    assert statuses["M1"].level == UNKNOWN and "Check motors" in statuses["M1"].text
    assert statuses["HB1"].level == UNKNOWN
    assert statuses["mpu"].level == OK


def test_hbridges_are_judged_from_their_two_motors():
    config = default_config()
    by_channel = {(e["hbridge"], e["channel"]): m for m, e in config["motors"].items()}
    results = {m: _ok("FL") for m in config["motors"]}
    results[by_channel[("HB2", "A")]] = _dead("FR")                                  # one channel dead
    results[by_channel[("HB3", "A")]] = results[by_channel[("HB3", "B")]] = _dead("BL")  # whole board dead
    del results[by_channel[("HB4", "B")]]                                            # not checked
    statuses = part_statuses(config, _telemetry(results=results))
    assert statuses["HB1"].level == OK
    assert statuses["HB2"].level == WARN and by_channel[("HB2", "A")] in statuses["HB2"].text
    assert statuses["HB3"].level == ERROR and "VM" in statuses["HB3"].text
    assert statuses["HB4"].level == OK and "wasn't checked" in statuses["HB4"].text
    assert statuses[by_channel[("HB2", "A")]].level == ERROR


def test_the_motor_being_checked_is_marked_busy():
    statuses = part_statuses(default_config(), _telemetry(results={}, state="running", current="M5"))
    assert statuses["M5"].level == WARN and statuses["M5"].text == "Checking now…"
    assert "Waiting" in statuses["M6"].text
    assert "checking motors" in summary(statuses)[0]


def test_summary_counts_and_names_failures():
    config = default_config()
    results = {m: _ok("FL") for m in config["motors"]}
    results["M7"] = _dead("BR")
    text, level = summary(part_statuses(config, _telemetry(results=results)))
    assert "Encoders 4/4" in text and "Motors 7/8 (M7 failed)" in text and level == ERROR
    results["M7"] = _ok("BR")
    assert summary(part_statuses(config, _telemetry(results=results)))[1] == OK
