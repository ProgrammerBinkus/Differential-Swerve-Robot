"""Check that every PWM channel, direction GPIO and I2C device in the config exists.

    python -m tools.probe_hardware

Read-only: direction pins are opened as inputs and nothing is driven.
"""

from __future__ import annotations

import glob
import os

from common.config import ENCODER_IDS, HBRIDGE_CHANNELS, HBRIDGE_IDS
from tools._common import load_config

OK, BAD = "  ok ", "  !! "


def probe_pwm(config: dict) -> None:
    print("PWM chips (/sys/class/pwm):")
    chips = {}
    for path in sorted(glob.glob("/sys/class/pwm/pwmchip*")):
        chip = int(path.rsplit("pwmchip", 1)[1])
        with open(os.path.join(path, "npwm")) as f:
            chips[chip] = int(f.read())
        device = os.path.realpath(os.path.join(path, "device"))
        print(f"      pwmchip{chip}: {chips[chip]} channels ({os.path.basename(device)})")
    if not chips:
        print(BAD + "none found. Enable the PWM overlays and reboot.")
    for hb in HBRIDGE_IDS:
        for channel in HBRIDGE_CHANNELS:
            pwm = config["hbridges"][hb][channel]["pwm"]
            exists = pwm["channel"] < chips.get(pwm["chip"], 0)
            print(f"{OK if exists else BAD}{hb}.{channel}: pwmchip{pwm['chip']}/pwm{pwm['channel']} "
                  f"(header pin {pwm.get('header_pin')}, {pwm.get('function')})")


def probe_gpio(config: dict) -> None:
    from periphery import GPIO, GPIOError

    print("\nDirection GPIOs:")
    chips = sorted(glob.glob("/dev/gpiochip*"))
    for hb in HBRIDGE_IDS:
        for channel in HBRIDGE_CHANNELS:
            spec = config["hbridges"][hb][channel]["dir"]
            label = f"{hb}.{channel}: {spec.get('name', '')} (header pin {spec.get('header_pin')})"
            candidates = [(spec["chip"], spec["line"])] if "chip" in spec else [(c, spec["name"]) for c in chips]
            for chip, line in candidates:
                try:
                    gpio = GPIO(chip, line, "in")
                except GPIOError:
                    continue
                print(f"{OK}{label} -> {chip} line {gpio.line}")
                gpio.close()
                break
            else:
                print(f"{BAD}{label} not found. Find it with `gpioinfo`, then set 'chip' and 'line'.")


def probe_i2c(config: dict) -> None:
    from periphery import I2C, I2CError

    print("\nI2C buses:", ", ".join(sorted(glob.glob("/dev/i2c-*"))) or "none")
    for encoder_id in ENCODER_IDS:
        bus = config["encoders"][encoder_id]["bus"]
        try:
            i2c = I2C(bus)
        except I2CError as exc:
            print(f"{BAD}{encoder_id} on {bus}: cannot open ({exc})")
            continue
        try:
            msgs = [I2C.Message([0x03]), I2C.Message([0, 0], read=True)]
            i2c.transfer(0x06, msgs)
            high, low = msgs[1].data
            print(f"{OK}{encoder_id} on {bus}: MT6701 at 0x06, raw angle {(high << 6) | (low >> 2)}")
        except I2CError as exc:
            print(f"{BAD}{encoder_id} on {bus}: no answer at 0x06 ({exc}). Check wiring and pull-ups.")
        if encoder_id == "E1":
            try:
                msgs = [I2C.Message([0x75]), I2C.Message([0], read=True)]
                i2c.transfer(0x68, msgs)
                print(f"{OK}MPU-6050 on {bus}: WHO_AM_I = 0x{msgs[1].data[0]:02x}")
            except I2CError:
                print(f"{BAD}MPU-6050 on {bus}: no answer at 0x68")
        i2c.close()


def main() -> None:
    config = load_config()
    probe_pwm(config)
    probe_gpio(config)
    probe_i2c(config)


if __name__ == "__main__":
    main()
