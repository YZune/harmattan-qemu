#!/bin/sh
# Build the original browser compatibility helper from pinned guest ABI inputs.
set -eu
test "$#" -eq 0 || exit 2
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ -n "${HARMATTAN_PREBUILT_HELPERS:-}" ]; then
    exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/prebuilt-helpers.py" browser
fi
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
out="$work_root/browser-guest"
link_root="$out/link-inputs"
mkdir -p "$link_root"
check_sha() {
    test "$(shasum -a 256 "$1" | cut -d ' ' -f 1)" = "$2" || {
        echo "Browser ABI input mismatch, retained: $1" >&2; exit 1;
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
# Validate the owners of the pinned qwk_1.0 API/layout; do not link them in.
extract_input grob /usr/bin/grob c0cd8e101827a2227d01a67388e1ae547ff76e9557f6e08b0178847952691cc6
extract_input libQtWebKit2experimental.so.4 /usr/lib/libQtWebKit2experimental.so.4.9.0 03a98f03623e1bdca3270fbff5147c1dc7cf63796dc3c47279154b8823a19ce4
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fPIC -shared -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined,-z,max-page-size=4096 \
    -Wl,-soname,n00-browser.so "$repo_root/scripts/harmattan-qemu/browser-guest.c" \
    "$link_root/libdl.so.2" "$link_root/libc.so.6" -o "$out/n00-browser.so"
file "$out/n00-browser.so"
shasum -a 256 "$out/n00-browser.so"
