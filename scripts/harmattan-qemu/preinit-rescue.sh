#!/bin/sh

export PATH=/sbin:/bin:/usr/sbin:/usr/bin

mount -o remount,rw / 2>/dev/null || true
mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true

mkdir -p /dev/pts /tmp /var/run /home
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount /dev/mmcblk0p3 /home 2>/dev/null || true

echo "HARMATTAN-HYBRID-RESCUE: PR1.3 rootfs on PR1.0 QEMU kernel" >/dev/ttyS0
echo "HARMATTAN-HYBRID-RESCUE: shell ready" >/dev/ttyS0

exec /bin/sh -i </dev/ttyS0 >/dev/ttyS0 2>&1
