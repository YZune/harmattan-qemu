#!/bin/sh

# Apply the official PR1.0 QEMU graphics adaptation to a PR1.3 root filesystem.
# Run this inside the derived Harmattan guest, never against a phone image.

set -eu

overlay=${1:-/tmp/qemu-ui-overlay.tar.gz}

if [ ! -f "$overlay" ]; then
    echo "Overlay not found: $overlay" >&2
    exit 1
fi

tar xzf "$overlay" -C /

# The archive contains a top-level directory entry. Keep the guest root
# traversable even if a third-party tar implementation preserves that mode.
chmod 0755 /

ln -sfn 2.6.32.26 /lib/modules/current

ln -sfn libEGL.so.1.3.0 /usr/lib/libEGL.so.1
ln -sfn libEGL.so.1.3.0 /usr/lib/libEGL.so
ln -sfn libGLES_CM.so.1.4.5 /usr/lib/libGLES_CM.so.1
ln -sfn libGLES_CM.so.1.4.5 /usr/lib/libGLES_CM.so
ln -sfn libGLESv2.so.1.4.9 /usr/lib/libGLESv2.so.1
ln -sfn libGLESv2.so.1.4.9 /usr/lib/libGLESv2.so

chmod 0644 /etc/X11/xorg.conf /etc/init/sgx.conf
chmod 0644 /usr/lib/xorg/modules/drivers/omapfb_drv.so
chmod 0644 /usr/lib/libEGL.so.1.3.0
chmod 0644 /usr/lib/libGLES_CM.so.1.4.5
chmod 0644 /usr/lib/libGLESv2.so.1.4.9
chmod 0755 /usr/local/sbin/start-pr13-qemu-ui
chmod 0755 /usr/local/libexec/harmattan-qemu/invoker-direct

# The rescue environment cannot recreate the Aegis credential attached to the
# packaged invoker, so stock applauncherd rejects every launcher request.  Keep
# the product binary recoverable and install the explicitly QEMU-only direct
# launcher.  Reapplying the overlay must never replace the backup with itself.
mkdir -p /usr/local/libexec/harmattan-qemu
if ! grep -q '^# HARMATTAN_QEMU_DIRECT_INVOKER$' /usr/bin/invoker 2>/dev/null; then
    cp -p /usr/bin/invoker /usr/local/libexec/harmattan-qemu/invoker.applauncherd
fi
cp /usr/local/libexec/harmattan-qemu/invoker-direct /usr/bin/invoker
chown 0:0 /usr/bin/invoker /usr/local/libexec/harmattan-qemu/invoker.applauncherd
chmod 0755 /usr/bin/invoker /usr/local/libexec/harmattan-qemu/invoker.applauncherd

# Rebuild Fontconfig once while creating the derived image.  The rescue boot
# has no RTC; use the overlay's own timestamp so the PR1.3 font directories and
# resulting cache are not permanently treated as files from the future.
if [ "$(date +%s)" -lt 1356998400 ]; then
    overlay_clock=$(date -r /usr/local/sbin/start-pr13-qemu-ui +%m%d%H%M%Y.%S 2>/dev/null || true)
    if [ -n "$overlay_clock" ]; then
        date "$overlay_clock" >/dev/null 2>&1 || true
    else
        date 010100002013.00 >/dev/null 2>&1 || true
    fi
fi
if command -v fc-cache >/dev/null 2>&1; then
    if ! fc-cache -f >/tmp/fontconfig-qemu.log 2>&1; then
        echo "Warning: Fontconfig cache rebuild failed; see /tmp/fontconfig-qemu.log" >&2
    fi
fi

# The production system relies on Aegis credentials for this helper.  That
# mechanism is absent under the PR1.0 QEMU kernel, so constrain the fallback
# to the messagebus group in this disposable derived image.
chown root:messagebus /usr/lib/dbus-1.0/dbus-daemon-launch-helper
chmod 4750 /usr/lib/dbus-1.0/dbus-daemon-launch-helper

chown 0:0 /usr/local/sbin/apply-pr13-qemu-ui-overlay
chown 0:0 /usr/local/sbin/start-pr13-qemu-ui
chown 0:0 /usr/local/libexec/harmattan-qemu/invoker-direct

sync

echo "PR1.3 QEMU UI overlay applied"
