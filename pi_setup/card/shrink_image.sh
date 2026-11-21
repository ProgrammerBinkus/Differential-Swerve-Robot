#!/bin/bash
# Turn a full-size card copy into a small image that fits any card of 8 GB or more: repair the
# filesystem, shrink the root partition, and switch Orange Pi's first-boot resize back on so the Pi
# grows it to fill the new card (it reboots once by itself to do that). Edits IMAGE in place, so work
# on a copy. Run as root in WSL:
#   sudo bash pi_setup/card/shrink_image.sh /mnt/c/pi/robot.img [size in GiB, default 6]
set -e
IMG="$1"; GIB="${2:-6}"; OFF=$((65536*512)); SIZE=$((GIB*1024*1024*1024))
[ -f "$IMG" ] || { echo "usage: $0 IMAGE.img [GiB]"; exit 1; }
for l in $(losetup -j "$IMG" | cut -d: -f1); do umount "$l" 2>/dev/null || true; losetup -d "$l"; done

L=$(losetup -f --show -o $OFF "$IMG")
MNT=$(mktemp -d)
trap 'cd /; umount "$MNT" 2>/dev/null || true; losetup -d "$L" 2>/dev/null || true; rmdir "$MNT"' EXIT

echo "=== repair (replays the journal left by a power cut)"
e2fsck -fy "$L" > /tmp/shrink_fsck.txt 2>&1 || true
tail -2 /tmp/shrink_fsck.txt
e2fsck -fn "$L" > /dev/null 2>&1 || { echo "still has errors after repair, stopping"; exit 1; }

echo "=== shrink the filesystem to $GIB GiB"
resize2fs "$L" "${GIB}G" 2>&1 | grep -i 'blocks long' || true
e2fsck -fn "$L" > /dev/null 2>&1 && echo "check after shrink: clean"

echo "=== first-boot resize back on"
mount "$L" "$MNT"
mkdir -p "$MNT/etc/systemd/system/basic.target.wants"
ln -sfn /lib/systemd/system/orangepi-resize-filesystem.service \
    "$MNT/etc/systemd/system/basic.target.wants/orangepi-resize-filesystem.service"
rm -f "$MNT/root/.no_rootfs_resize"
umount "$MNT"; losetup -d "$L"

echo "=== partition table and file size"
echo "65536,$((SIZE/512)),83" | sfdisk --no-reread --no-tell-kernel -N 1 "$IMG" > /dev/null
truncate -s $((OFF + SIZE)) "$IMG"
sfdisk -l "$IMG" | tail -1
ls -l "$IMG"

L=$(losetup -f --show -r -o $OFF --sizelimit $SIZE "$IMG")
e2fsck -fn "$L" 2>&1 | tail -1
echo "done: flash $IMG with Raspberry Pi Imager (Use custom)"
