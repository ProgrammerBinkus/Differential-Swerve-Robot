#!/bin/bash
# Install the i2c-100khz user overlay (encoder buses at 100 kHz) and reboot to load it, on a Pi set
# up before setup.sh did this itself. Run on the Pi next to i2c-100khz.dtbo: sudo bash i2c_speed.sh
# Undo: remove i2c-100khz from the user_overlays= line in /boot/orangepiEnv.txt and reboot.
set -e
cd "$(dirname "$0")"
ENV=/boot/orangepiEnv.txt
test -s i2c-100khz.dtbo
mkdir -p /boot/overlay-user
install -m 644 i2c-100khz.dtbo /boot/overlay-user/i2c-100khz.dtbo
cp "$ENV" "$ENV.before-i2c-speed"
if grep -q '^user_overlays=' "$ENV"; then
  grep -q '^user_overlays=.*\bi2c-100khz\b' "$ENV" || sed -i 's/^user_overlays=\(.*\)$/user_overlays=\1 i2c-100khz/' "$ENV"
else
  echo "user_overlays=i2c-100khz" >> "$ENV"
fi
sync
cat "$ENV"
echo "Rebooting in 3 s to load it."
sleep 3
systemctl reboot
