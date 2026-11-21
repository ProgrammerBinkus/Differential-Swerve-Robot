#!/bin/bash
# Check a copy of the Pi's SD card without changing it: filesystem check, boot files, boot settings,
# and when Linux last mounted it. Run as root in WSL:
#   sudo bash pi_setup/card/inspect_card.sh /mnt/c/pi/card.img
IMG="$1"; OFF=$((65536*512))
[ -f "$IMG" ] || { echo "usage: $0 CARD.img"; exit 1; }
L=$(losetup -f --show -r -o $OFF "$IMG")
MNT=$(mktemp -d)
trap 'cd /; umount "$MNT" 2>/dev/null; losetup -d "$L"; rmdir "$MNT"' EXIT

echo "=== boot loader: non-zero bytes in the 32 MB before the partition (0 = missing)"
dd if="$IMG" bs=1M count=32 status=none | tr -d '\0' | wc -c

echo "=== superblock (Last mount time = the last boot that reached Linux; times in this PC's zone)"
dumpe2fs -h "$L" 2>/dev/null | grep -E 'Filesystem features|Filesystem state|Last mount time|Last write time|Mount count|Block count|Free blocks'

echo "=== e2fsck -fn (read-only; after a power cut it lists problems the Pi's own boot would repair)"
e2fsck -fn "$L" > /tmp/inspect_fsck.txt 2>&1; rc=$?
grep -E '^(File|Unattached|Free|Inode|Pass)|WARNING|files \(' /tmp/inspect_fsck.txt | head -40
echo "e2fsck exit=$rc (0 = clean, 4 = errors left uncorrected)"

mount -o ro,noload "$L" "$MNT" || { echo "MOUNT FAILED"; exit 1; }
cd "$MNT"
echo "=== /boot/orangepiEnv.txt"; cat boot/orangepiEnv.txt
echo "=== boot files"
for f in boot/boot.scr boot/uImage boot/uInitrd boot/dtb/allwinner/sun60i-a733-orangepi-4-pro.dtb; do
  [ -e "$f" ] || { echo "MISSING $f"; continue; }
  echo "$f: $(stat -L -c %s "$f") bytes, starts $(head -c4 "$f" | xxd -p)"
done
echo "(uImage and uInitrd should start 27051956, the .dtb d00dfeed)"
for o in $(grep '^overlays=' boot/orangepiEnv.txt | cut -d= -f2); do
  f=boot/dtb/allwinner/overlay/sun60i-a733-$o.dtbo
  [ "$(head -c4 "$f" 2>/dev/null | xxd -p)" = d00dfeed ] || echo "BAD OR MISSING overlay $f"
done
echo "=== newest log files"
ls -lt var/log | head -8
