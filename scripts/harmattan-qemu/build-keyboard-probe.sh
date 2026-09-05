#!/bin/sh
# Build a read-only SQLite inspector for the disposable Notes input test.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
out="$work_root/keyboard-probe"
mkdir -p "$out"
extract_dir=$(mktemp -d "$out/link.XXXXXX")
rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
(cd "$extract_dir" && "$debugfs_bin" -R 'dump /usr/lib/libsqlite3.so.0.8.6 libsqlite3.so.0' "$rootfs" &&
 "$debugfs_bin" -R 'dump /lib/libc-2.10.1.so libc.so.6' "$rootfs")
test "$(shasum -a 256 "$extract_dir/libsqlite3.so.0" | cut -d ' ' -f 1)" = a2d641e648baaa7c2097be760470bd7be3877db9e395046da42bfeaa2794d897
test "$(shasum -a 256 "$extract_dir/libc.so.6" | cut -d ' ' -f 1)" = 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fno-pie -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined \
    -Wl,-no-pie,--dynamic-linker=/lib/ld-linux.so.3,-z,max-page-size=4096 \
    "$repo_root/scripts/harmattan-qemu/start-armel-libc.S" \
    "$repo_root/scripts/harmattan-qemu/keyboard-notes-read.c" \
    "$extract_dir/libsqlite3.so.0" "$extract_dir/libc.so.6" -o "$out/keyboard-notes-read"
shasum -a 256 "$out/keyboard-notes-read"
