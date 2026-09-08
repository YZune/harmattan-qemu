#!/bin/sh
# Build only a small helper; do not rebuild QEMU or replace guest libraries.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
if [ -n "${HARMATTAN_PREBUILT_HELPERS:-}" ]; then
    test "$#" -eq 0 || exit 2
    echo 'Call simulation currently requires a source build and guest linking inputs.' >&2; exit 2
fi
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
out="$work_root/call-simulation-guest"
link_root="$out/link-inputs"
test "$#" -eq 0 || exit 2
mkdir -p "$link_root"
rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
check_sha() {
    test "$(shasum -a 256 "$1" | cut -d ' ' -f 1)" = "$2" || {
        echo "Guest library hash mismatch, retained: $1" >&2; exit 1;
    }
}
extract_input() {
    input_name=$1
    guest_path=$2
    expected=$3
    if [ ! -e "$link_root/$input_name" ]; then
        extract_dir=$(mktemp -d "$link_root/.extract.XXXXXX")
        (cd "$extract_dir" && "$debugfs_bin" -R "dump $guest_path $input_name" "$rootfs")
        check_sha "$extract_dir/$input_name" "$expected"
        mv -n "$extract_dir/$input_name" "$link_root/$input_name"
    fi
    check_sha "$link_root/$input_name" "$expected"
}
extract_input libdbus-1.so.3 /usr/lib/libdbus-1.so.3.5.4 322d79b75dcb63b25537fe4107fc2dae0f77ad0bc50c2d7da683750c8f0cea34
extract_input libgstreamer-0.10.so.0 /usr/lib/libgstreamer-0.10.so.0.29.0 412f5305eaeff5de58d9906331f186cd1ec81cd9475dc32b3213ec80404c11c6
extract_input libc.so.6 /lib/libc-2.10.1.so 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fno-pie -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined \
    -Wl,-no-pie,--dynamic-linker=/lib/ld-linux.so.3,-z,max-page-size=4096 \
    "$repo_root/scripts/harmattan-qemu/start-armel-libc.S" \
    "$repo_root/scripts/harmattan-qemu/call-simulation-guest.c" \
    "$link_root/libdbus-1.so.3" "$link_root/libgstreamer-0.10.so.0" "$link_root/libc.so.6" \
    -o "$out/n00-call-simulation"
file "$out/n00-call-simulation"
shasum -a 256 "$out/n00-call-simulation"
