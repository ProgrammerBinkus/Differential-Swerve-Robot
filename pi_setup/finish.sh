#!/bin/bash
# Last admin step: PWM permissions, the Pi's network name, and the robot program starting on boot.
set -e
cd "$(dirname "$0")"
pkill -f "main.py robot" || true   # stop the test copy started earlier

echo "== 1/3 PWM permissions"
bash pwm_perms.sh

echo "== 2/3 Network name (orangepi4pro.local)"
apt-get install -y avahi-daemon >/dev/null
systemctl enable --now avahi-daemon
systemctl is-active avahi-daemon

echo "== 3/3 Robot program starts on boot"
ln -sfn "/home/orangepi/Differential Swerve Chassis" /home/orangepi/robot
chown -h orangepi:orangepi /home/orangepi/robot
cat > /etc/systemd/system/swerve-robot.service <<'EOF'
[Unit]
Description=Differential swerve robot
After=network-online.target robot-pwm-perms.service
Wants=network-online.target

[Service]
User=orangepi
WorkingDirectory=/home/orangepi/robot
ExecStart=/home/orangepi/robot/venv/bin/python main.py robot
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
# Let orangepi start, stop and restart only this service, and power off, without a password.
bash sudoers.sh
systemctl daemon-reload
systemctl enable --now swerve-robot.service
sleep 5
systemctl status swerve-robot.service --no-pager | head -12
echo "All done."
