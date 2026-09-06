#!/bin/sh
# Build the bounded Qt viewport adapter from verified guest ABI inputs.
set -eu
test "$#" -eq 0 || exit 2
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -n "${HARMATTAN_PREBUILT_HELPERS:-}" ]; then
    exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/prebuilt-helpers.py" app-viewport
fi
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
out="$work_root/app-viewport-guest"
link_root="$out/link-inputs"
mkdir -p "$link_root"
check_sha() {
    test "$(shasum -a 256 "$1" | cut -d ' ' -f 1)" = "$2" || {
        echo "Application viewport ABI input mismatch, retained: $1" >&2; exit 1;
    }
}
extract_input() {
    name=$1; guest=$2; expected=$3
    if [ ! -e "$link_root/$name" ]; then
        temporary=$(mktemp -d "$link_root/.extract.XXXXXX")
        (cd "$temporary" && "$debugfs_bin" -R "dump $guest $name" "$rootfs")
        check_sha "$temporary/$name" "$expected"
        mv -n "$temporary/$name" "$link_root/$name"
    fi
    check_sha "$link_root/$name" "$expected"
}
extract_input libc.so.6 /lib/libc-2.10.1.so 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
extract_input libdl.so.2 /lib/libdl-2.10.1.so 46e89f3e896c176377ee1aca99ce27a33cc6dc3820ed6235403ed0fefe234149
# These API owners are resolved at runtime, not linked into the helper.
extract_input libQtCore.so.4 /usr/lib/libQtCore.so.4.7.4 0fc6e2823ec376813d3e1f23a430f05748c4ee6fa05629a6b5211ab18002a52a
extract_input libQtGui.so.4 /usr/lib/libQtGui.so.4.7.4 b5d9900f445eccb8d008b49fd0fa7b057f6ea7a8069ebdec5fe515e7bc27d49b
extract_input libQtOpenGL.so.4 /usr/lib/libQtOpenGL.so.4.7.4 39dc6079440d1a6d9b1e2c08b34e0f6db6d3664b88e7465a5470bc66203c3b18
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fPIC -shared -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined,-z,max-page-size=4096 \
    -Wl,-soname,n00-app-viewport.so "$repo_root/scripts/harmattan-qemu/app-viewport-guest.c" \
    "$link_root/libdl.so.2" "$link_root/libc.so.6" -o "$out/n00-app-viewport.so"
file "$out/n00-app-viewport.so"
shasum -a 256 "$out/n00-app-viewport.so"
