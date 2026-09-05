#!/bin/sh

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
adaptation_dir="$repo_root/extracted/pr1.0-qemu-adaptation"
source_archive="$adaptation_dir/qemu-adaptation.tar.gz"
output_archive="$adaptation_dir/qemu-ui-overlay.tar.gz"
stage_dir=$(mktemp -d /tmp/harmattan-qemu-overlay.XXXXXX)
chmod 0755 "$stage_dir"

cleanup() {
    rm -rf "$stage_dir"
}
trap cleanup EXIT HUP INT TERM

tar xzf "$source_archive" -C "$stage_dir" \
    lib/modules/2.6.32.26 \
    etc/X11/xorg.conf \
    etc/init/sgx.conf

mkdir -p \
    "$stage_dir/usr/lib/xorg/modules/drivers" \
    "$stage_dir/usr/local/libexec/harmattan-qemu" \
    "$stage_dir/usr/local/sbin"

cp -p "$adaptation_dir/usr/lib/xorg/modules/drivers/omapfb_drv.so" \
    "$stage_dir/usr/lib/xorg/modules/drivers/omapfb_drv.so"
cp -p "$adaptation_dir/usr/lib/libEGL.so.1.3.0" "$stage_dir/usr/lib/"
cp -p "$adaptation_dir/usr/lib/libGLES_CM.so.1.4.5" "$stage_dir/usr/lib/"
cp -p "$adaptation_dir/usr/lib/libGLESv2.so.1.4.9" "$stage_dir/usr/lib/"
cp -p "$repo_root/scripts/harmattan-qemu/xorg-pr13-qemu.conf" \
    "$stage_dir/etc/X11/xorg.conf"
cp -p "$repo_root/scripts/harmattan-qemu/start-pr13-qemu-ui.sh" \
    "$stage_dir/usr/local/sbin/start-pr13-qemu-ui"
cp -p "$repo_root/scripts/harmattan-qemu/invoker-direct-qemu.sh" \
    "$stage_dir/usr/local/libexec/harmattan-qemu/invoker-direct"
cp -p "$repo_root/scripts/harmattan-qemu/apply-pr13-ui-overlay.sh" \
    "$stage_dir/usr/local/sbin/apply-pr13-qemu-ui-overlay"

COPYFILE_DISABLE=1 tar --no-xattrs --format ustar --uid 0 --gid 0 \
    -czf "$output_archive" -C "$stage_dir" .

echo "Created $output_archive"
sha1sum "$output_archive"
