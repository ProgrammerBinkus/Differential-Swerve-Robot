#!/bin/bash
# Let the orangepi user (and so the robot code) use the I2C buses and GPIO pins without sudo.
# PWM permissions are set up by pwm_perms.sh. Run with: sudo bash perms.sh
set -e
groupadd -f gpio
usermod -aG i2c,gpio orangepi
id orangepi
echo "Done. Group changes apply to new logins."
