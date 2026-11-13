#!/bin/bash
# One-time Orange Pi setup for the swerve robot. Run with: sudo bash setup.sh
# Needs the three HDMI fix files next to it (hdmi-console-restore, hdmi-console-restore.service,
# 99-hdmi-console-restore.rules) from https://github.com/CheezeCS/armbian-a733-gpu/tree/main/files/hdmi-fix
set -e
cd "$(dirname "$0")"

echo "== 1/4 Packages"
apt-get update
apt-get install -y i2c-tools gpiod python3-venv libdrm-tests

echo "== 2/4 HDMI fix (screen comes back when the monitor reconnects)"
install -m 755 hdmi-console-restore /usr/local/sbin/
install -m 644 hdmi-console-restore.service /etc/systemd/system/
install -m 644 99-hdmi-console-restore.rules /etc/udev/rules.d/
systemctl daemon-reload
systemctl enable hdmi-console-restore.service
udevadm control --reload-rules
# Boot to the text console: the fix works there, and the robot needs no desktop.
systemctl set-default multi-user.target

echo "== 3/4 Turn on the I2C buses and PWM pins the robot uses"
ENV=/boot/orangepiEnv.txt
cp -n "$ENV" "$ENV.before-robot"
LINE="overlays=i2c0 i2c1 i2c2 i2c3 pwm0 pwm2 pwm3 pwm4 pwm5 pwm6 pwm7 spwm2"
if grep -q '^overlays=' "$ENV"; then sed -i "s/^overlays=.*/$LINE/" "$ENV"; else echo "$LINE" >> "$ENV"; fi
for o in i2c0 i2c1 i2c2 i2c3 pwm0 pwm2 pwm3 pwm4 pwm5 pwm6 pwm7 spwm2; do
  test -f "/boot/dtb/allwinner/overlay/sun60i-a733-$o.dtbo" || { echo "missing overlay $o"; exit 1; }
done
cat "$ENV"

echo "== 4/4 Robot Python environment"
sudo -u orangepi bash -c 'cd ~/"Differential Swerve Chassis" && python3 -m venv venv && venv/bin/pip install -q -r requirements-robot.txt && venv/bin/python -c "from wpimath.kinematics import SwerveDrive4Kinematics; print(\"wpimath OK\")"'

echo "== Done. Rebooting in 5 s to load the I2C and PWM settings."
sleep 5
reboot
