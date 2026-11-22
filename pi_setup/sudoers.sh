#!/bin/bash
# What the orangepi user (and so the robot program) may run as root without a password:
# start, stop and restart the robot service (code updates, bring-up tools), and power the Pi off
# (the driver station's Power off button). Nothing else. Run with: sudo bash sudoers.sh
set -e
RULES=/etc/sudoers.d/swerve-robot
NEW=$(mktemp)
cat > "$NEW" <<'EOF'
orangepi ALL=(root) NOPASSWD: /usr/bin/systemctl restart swerve-robot.service, /usr/bin/systemctl stop swerve-robot.service, /usr/bin/systemctl start swerve-robot.service, /usr/bin/systemctl poweroff
EOF
visudo -cf "$NEW"          # never install a rules file sudo can't read: it would lock sudo out
install -m 440 -o root -g root "$NEW" "$RULES"
rm -f "$NEW"
echo "Installed $RULES:"
cat "$RULES"
