"""Copy the H-bridge pin map from common/config.py into robot_config.json, keeping everything else.

robot_config.json overrides the defaults, so after the pins are changed in code (a rewiring), run:

    python -m tools.sync_hbridge_pins [path/to/robot_config.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common.config import default_config


def sync(path: Path) -> list[str]:
    """Rewrite ``path``'s "hbridges" section; return a line per channel that changed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    new = default_config()["hbridges"]
    old = data.get("hbridges", {})
    changes = []
    for hb, channels in new.items():
        for channel, spec in channels.items():
            before = old.get(hb, {}).get(channel)
            if before != spec:
                pins = lambda s: f"PWM {s['pwm']['header_pin']} + DIR {s['dir']['header_pin']} ({s['dir']['name']})"
                changes.append(f"{hb}.{channel}: {pins(before) if before else 'none'} -> {pins(spec)}")
    data["hbridges"] = new
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changes


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "robot_config.json")
    for line in sync(target) or ["already up to date"]:
        print(line)
