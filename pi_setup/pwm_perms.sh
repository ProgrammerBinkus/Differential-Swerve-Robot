#!/bin/bash
# Fix PWM permissions: let the gpio group export PWM channels and set their period, duty and enable.
set -e
cat > /usr/local/sbin/robot-pwm-perms <<'EOF'
#!/bin/sh
# Give the gpio group the PWM sysfs files the robot writes (run by udev on PWM events, and at boot).
for chip in /sys/class/pwm/pwmchip*; do
  for f in "$chip/export" "$chip/unexport" "$chip"/pwm*/period "$chip"/pwm*/duty_cycle "$chip"/pwm*/enable "$chip"/pwm*/polarity; do
    [ -e "$f" ] || continue
    chgrp gpio "$f" && chmod g+rw "$f"
  done
done
EOF
chmod 755 /usr/local/sbin/robot-pwm-perms
cat > /etc/udev/rules.d/90-robot-gpio-pwm.rules <<'EOF'
# Robot pins: GPIO character devices and PWM sysfs files for the gpio group.
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
SUBSYSTEM=="pwm", RUN+="/usr/local/sbin/robot-pwm-perms"
EOF
cat > /etc/systemd/system/robot-pwm-perms.service <<'EOF'
[Unit]
Description=Give the gpio group access to the PWM outputs
After=systemd-udev-settle.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/robot-pwm-perms

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now robot-pwm-perms.service
udevadm control --reload-rules
ls -l /sys/class/pwm/pwmchip0/export /sys/class/pwm/pwmchip20/export
echo "Done."
