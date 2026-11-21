# Copy the robot code from this PC to the Pi (keeping the Pi's venv), then restart the robot program.
# Run from the project folder: powershell -ExecutionPolicy Bypass -File pi_setup\sync.ps1
# The Pi's robot_config.json is kept (mapping, offsets, tuning), except its H-bridge pins, which
# always follow common/config.py: those only change when the robot is rewired.
param([string]$PiHost = "orangepi4pro.local")
$src = Split-Path -Parent $PSScriptRoot
$tar = Join-Path $env:TEMP "robot-sync.tar"
tar.exe -cf $tar -C $src --exclude=__pycache__ common robot tools tests main.py requirements-robot.txt README.md pytest.ini
$opts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")
scp -q @opts $tar "orangepi@${PiHost}:robot-sync.tar"
ssh @opts "orangepi@$PiHost" "cd ~/robot && tar -xf ~/robot-sync.tar && rm ~/robot-sync.tar && { [ ! -f robot_config.json ] || venv/bin/python -m tools.sync_hbridge_pins; } && sudo -n systemctl restart swerve-robot.service && echo 'synced and restarted'"
Remove-Item $tar
