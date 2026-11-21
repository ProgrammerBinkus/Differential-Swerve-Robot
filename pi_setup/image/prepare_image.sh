#!/bin/bash
# Prepare a freshly downloaded Orange Pi image before flashing it, so the Pi joins Wi-Fi on first boot
# and this PC can log in over SSH straight away (no monitor or keyboard needed).
#
# Run as root in WSL (Ubuntu), from the project folder:
#   sudo bash pi_setup/image/prepare_image.sh IMAGE.img ~/.ssh/id_ed25519.pub [wifi.nmconnection]
#
#   IMAGE.img          the unpacked Orange Pi .img file (edited in place)
#   id_ed25519.pub     this PC's public SSH key (create one with: ssh-keygen -t ed25519)
#   wifi.nmconnection  optional: a filled-in copy of wifi.nmconnection.example (holds the Wi-Fi password;
#                      keep it out of git and delete it after use)
#
# It copies the robot project into ~orangepi/Differential Swerve Chassis. Afterwards run
# pi_setup/setup.sh on the Pi (see docs/orange-pi.md).
set -e
IMG="$1"; PUBKEY="$2"; WIFI="$3"
[ -f "$IMG" ] && [ -f "$PUBKEY" ] || { echo "usage: $0 IMAGE.img PUBKEY.pub [wifi.nmconnection]"; exit 1; }
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
MNT=/mnt/opi
OFF=$((65536*512))   # Orange Pi images: the root partition starts at sector 65536

if [ -n "$WIFI" ]; then
  grep -q 'TYPE_YOUR_WIFI' "$WIFI" && { echo "fill in the Wi-Fi name and password in $WIFI first"; exit 1; }
  for key in ssid psk; do grep -q "^$key=." "$WIFI" || { echo "$WIFI: the $key= line is empty"; exit 1; }; done
fi

mkdir -p $MNT
mountpoint -q $MNT || mount -o loop,offset=$OFF "$IMG" $MNT
trap 'cd /; sync; umount $MNT 2>/dev/null || true' EXIT
test -f $MNT/etc/os-release || { echo "that doesn't look like an Orange Pi image"; exit 1; }
echo "image: $(grep PRETTY_NAME $MNT/etc/os-release | cut -d= -f2), hostname $(cat $MNT/etc/hostname)"

# SSH: let this PC log in as orangepi (uid 1000) without a password.
install -d -m 700 -o 1000 -g 1000 $MNT/home/orangepi/.ssh
install -m 600 -o 1000 -g 1000 "$PUBKEY" $MNT/home/orangepi/.ssh/authorized_keys
echo "SSH key added"

# Wi-Fi: a NetworkManager connection. Notepad may add a byte-order mark and Windows line endings.
if [ -n "$WIFI" ]; then
  OUT=$MNT/etc/NetworkManager/system-connections/robot-wifi.nmconnection
  sed '1s/^\xEF\xBB\xBF//' "$WIFI" | tr -d '\r' > "$OUT"
  chown root:root "$OUT"; chmod 600 "$OUT"
  echo "Wi-Fi connection added (ssid $(grep '^ssid=' "$OUT" | cut -d= -f2- | tr -d '\n' | wc -c) characters long)"
fi

# Robot code: the project without Windows-only and machine-local folders.
DST="$MNT/home/orangepi/Differential Swerve Chassis"
rm -rf "$DST"; mkdir -p "$DST"
tar -C "$SRC" --exclude=./venv --exclude=./dist --exclude=./build --exclude=./.git \
    --exclude='__pycache__' --exclude=./.pytest_cache --exclude=./robot_config.json \
    --exclude=./station_settings.json -cf - . | tar -C "$DST" -xf -
chown -R 1000:1000 "$DST"
echo "robot code copied ($(du -sh "$DST" | cut -f1))"
