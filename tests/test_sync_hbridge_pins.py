"""tools.sync_hbridge_pins: robot_config.json takes the code's H-bridge pins and keeps everything else."""

import json

from common.config import default_config
from tools.sync_hbridge_pins import sync


def test_sync_replaces_only_the_hbridge_pins(tmp_path):
    config = default_config()
    config["hbridges"]["HB4"]["B"]["dir"] = {"name": "PL12", "header_pin": 13}   # the old wiring
    config["modules"]["FL"]["offset"] = 1234                                       # set on the robot
    path = tmp_path / "robot_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert sync(path) == ["HB4.B: PWM 7 + DIR 13 (PL12) -> PWM 7 + DIR 8 (PL6)"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["hbridges"] == default_config()["hbridges"]
    assert saved["modules"]["FL"]["offset"] == 1234
    assert sync(path) == []                                                        # nothing left to change
