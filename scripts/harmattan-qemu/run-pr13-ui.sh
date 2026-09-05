#!/bin/sh

# Launch the persistent PR1.3-on-PR1.0 hybrid image with Nokia's N00 QEMU.
# The guest boots to a rescue shell; run start-pr13-qemu-ui there.

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
qemu_root="$repo_root/downloads/internet-archive/qtsdk-1.1.2-mac-components/qemu-snow-leopard-2011-06-09"
qemu="$qemu_root/bin/qemu-system-arm"
skin="$qemu_root/share/qemu/skin/glow/skin.xml"
nand="$repo_root/extracted/hybrid-pr1.3-qemu/arm-qemu-rm680-nand-pr1.3-ui.qcow2"
sd="$repo_root/extracted/hybrid-pr1.3-qemu/arm-qemu-rm680-image-pr1.3-ui.raw"
monitor_socket=${HARMATTAN_MONITOR_SOCKET:-/tmp/harmattan-pr13-ui-monitor.sock}

for required in "$qemu" "$skin" "$nand" "$sd"; do
    if [ ! -e "$required" ]; then
        echo "Required runtime file not found: $required" >&2
        exit 1
    fi
done

if [ -e "$monitor_socket" ]; then
    if [ ! -S "$monitor_socket" ]; then
        echo "Refusing to replace a non-socket monitor path: $monitor_socket" >&2
        exit 1
    fi
    if lsof "$monitor_socket" >/dev/null 2>&1; then
        echo "A QEMU monitor is already using: $monitor_socket" >&2
        exit 1
    fi
    rm -f "$monitor_socket"
fi

cd "$repo_root"

echo "The QEMU display remains black while the PR1.3 rescue system boots."
echo "When the serial console shows '/ #', run:"
echo "  /usr/local/sbin/start-pr13-qemu-ui"
echo

# The PR1.3 Qt/MeeGo Touch working set repeatedly fills QEMU 0.13's
# approximately 32 MiB default translation buffer.  A verified 64 MiB buffer
# reduced full TB flushes from six to two at the same cold-UI checkpoint while
# remaining compatible with this old Cocoa build under Rosetta.
exec arch -x86_64 /usr/bin/env \
    DYLD_LIBRARY_PATH="$qemu_root/lib" \
    "$qemu" \
    -tb-size 64 \
    -M n00 \
    -portrait \
    -skin "$skin" \
    -mtdblock "$nand" \
    -sd "$sd" \
    -serial stdio \
    -monitor "unix:$monitor_socket,server,nowait" \
    -net nic \
    -net user
