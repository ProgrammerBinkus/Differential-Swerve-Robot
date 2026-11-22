"""Spin motors one at a time, or test a module's drive/steer mix, to set the invert flags.

    python -m tools.motor_test motor M3 --duty 0.2
    python -m tools.motor_test module FL --amount 0.25

``motor`` runs one motor forward, then reverse, and reports how far its
module's steering moved. ``module`` runs pure drive, then pure steer, and
says which invert flags to change. Wheels must be off the ground.
"""

from __future__ import annotations

import argparse
import math
import time

from common.config import MODULE_NAMES, MOTOR_IDS, module_of_motor
from robot.hardware import open_hardware
from robot.swerve.mixing import mix
from robot.swerve.steering_angle import SteeringAngleTracker
from tools._common import confirm_wheels_off_ground, load_config, robot_program_paused

STEP_S = 0.01


def _run(outputs, tracker, encoder, commands, seconds) -> float:
    """Apply commands to outputs for ``seconds``; return the steering change in degrees."""
    tracker.update(encoder.read_raw())
    start = tracker.angle_rad
    end_time = time.monotonic() + seconds
    while time.monotonic() < end_time:
        for output, command in zip(outputs, commands):
            output.set(command)
        tracker.update(encoder.read_raw())
        time.sleep(STEP_S)
    for output in outputs:
        output.stop()
    time.sleep(0.5)  # let it coast down before the next step
    tracker.update(encoder.read_raw())
    return math.degrees(tracker.angle_rad - start)


def test_motor(config, hardware, motor_id: str, duty: float, seconds: float) -> None:
    output = hardware.output_for_motor(config, motor_id)
    slot = module_of_motor(config, motor_id)
    module = config["modules"][slot[0]] if slot else None
    encoder = hardware.encoders[module["encoder"]] if module else None
    tracker = SteeringAngleTracker(module["offset"], module["invert_encoder"]) if module else None
    for label, command in (("forward", duty), ("reverse", -duty)):
        print(f"{motor_id} {label} at {abs(command):.0%} for {seconds:.1f} s ...")
        if encoder:
            moved = _run([output], tracker, encoder, [command], seconds)
            print(f"   module {slot[0]} steering moved {moved:+.1f}°")
        else:
            output.set(command)
            time.sleep(seconds)
            output.stop()
            time.sleep(0.5)


def test_module(config, hardware, name: str, amount: float, seconds: float) -> None:
    module = config["modules"][name]
    outputs = [hardware.output_for_motor(config, module["motor_a"]),
               hardware.output_for_motor(config, module["motor_b"])]
    signs = [-1.0 if module["invert_a"] else 1.0, -1.0 if module["invert_b"] else 1.0]
    encoder = hardware.encoders[module["encoder"]]
    tracker = SteeringAngleTracker(module["offset"], module["invert_encoder"])

    def commands(drive: float, steer: float) -> list[float]:
        return [sign * value for sign, value in zip(signs, mix(drive, steer))]

    print(f"{name}: pure drive {amount:.0%} - the wheel should roll forward and NOT steer ...")
    drive_moved = _run(outputs, tracker, encoder, commands(amount, 0.0), seconds)
    print(f"   steering moved {drive_moved:+.1f}°")
    print(f"{name}: pure steer {amount:.0%} - the wheel should turn counter-clockwise (seen from above) ...")
    steer_moved = _run(outputs, tracker, encoder, commands(0.0, amount), seconds)
    print(f"   steering moved {steer_moved:+.1f}°")

    print("\nResult:")
    if abs(drive_moved) > max(10.0, abs(steer_moved) / 2):
        print(f" - Pure drive steered the wheel: flip ONE of invert_a / invert_b for {name}.")
    elif steer_moved < 0:
        print(f" - Steering went the wrong way: swap motor_a and motor_b for {name} "
              "(or flip invert_encoder if the encoder reads backwards).")
    else:
        print(" - Drive and steer are separated and steering is positive. Good.")
    print(" - If the wheel rolled backward on pure drive, flip BOTH invert_a and invert_b.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="motor_test", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    motor = sub.add_parser("motor", help="spin one motor forward then reverse")
    motor.add_argument("motor_id", choices=MOTOR_IDS)
    motor.add_argument("--duty", type=float, default=0.2)
    module = sub.add_parser("module", help="test one module's drive/steer mix")
    module.add_argument("module", choices=MODULE_NAMES)
    module.add_argument("--amount", type=float, default=0.25)
    for p in (motor, module):
        p.add_argument("--seconds", type=float, default=1.5)
    args = parser.parse_args()

    config = load_config()
    confirm_wheels_off_ground()
    with robot_program_paused():
        hardware = open_hardware(config, simulate=False)
        try:
            if args.mode == "motor":
                test_motor(config, hardware, args.motor_id, min(abs(args.duty), 1.0), args.seconds)
            else:
                test_module(config, hardware, args.module, min(abs(args.amount), 1.0), args.seconds)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            hardware.close()


if __name__ == "__main__":
    main()
