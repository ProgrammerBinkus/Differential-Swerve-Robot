"""Print every encoder's raw reading and steering angle at 10 Hz (Ctrl+C to stop).

    python -m tools.encoder_monitor

Turn each wheel by hand: the raw value should change smoothly through
0-16383 and wrap once per half turn of the wheel, and one full wheel turn
should change the angle by 360 degrees.
"""

from __future__ import annotations

import math
import time

from common.config import MODULE_NAMES
from robot.hardware.encoder import MT6701
from robot.swerve.steering_angle import SteeringAngleTracker
from tools._common import load_config


def main() -> None:
    config = load_config()
    readers = {}
    for name in MODULE_NAMES:
        module = config["modules"][name]
        bus = config["encoders"][module["encoder"]]["bus"]
        readers[name] = (MT6701(bus), SteeringAngleTracker(module["offset"], module["invert_encoder"]))
    print("  ".join(f"{name:>16}" for name in MODULE_NAMES))
    try:
        while True:
            cells = []
            for name, (encoder, tracker) in readers.items():
                try:
                    raw = encoder.read_raw()
                except OSError:
                    cells.append(f"{'read error':>16}")
                    continue
                tracker.update(raw)
                cells.append(f"{raw:5d} {math.degrees(tracker.angle_rad):+9.1f}°")
            print("  ".join(cells), end="\r", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        for encoder, _ in readers.values():
            encoder.close()


if __name__ == "__main__":
    main()
