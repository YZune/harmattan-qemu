#!/bin/sh
# Build only a small helper; do not rebuild QEMU or replace guest libraries.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
if [ -n "${HARMATTAN_PREBUILT_HELPERS:-}" ]; then
    test "$#" -eq 0 || exit 2
    exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/prebuilt-helpers.py" orientation
fi
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
out="$work_root/orientation-guest"
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
extract_input libcontextprovider.so.0 /usr/lib/libcontextprovider.so.0.0.0 2a410dac7435db5e79351a959087f6ead56d51ebba5c350bb70151a3270ca3bd
extract_input libglib-2.0.so.0 /lib/libglib-2.0.so.0.2800.4 4424cd79abc8e1fc1065aebc4ee15c777da1f5777f896cb81c5e95a1ac186c22
extract_input libc.so.6 /lib/libc-2.10.1.so 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fno-pie -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined \
    -Wl,-no-pie,--dynamic-linker=/lib/ld-linux.so.3,-z,max-page-size=4096 \
    "$repo_root/scripts/harmattan-qemu/start-armel-libc.S" \
    "$repo_root/scripts/harmattan-qemu/orientation-provider-guest.c" \
    "$link_root/libcontextprovider.so.0" "$link_root/libglib-2.0.so.0" "$link_root/libc.so.6" \
    -o "$out/n00-orientation-provider"
file "$out/n00-orientation-provider"
shasum -a 256 "$out/n00-orientation-provider"
