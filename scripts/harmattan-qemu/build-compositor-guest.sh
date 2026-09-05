#!/bin/sh
# Tiny snapshot-local compatibility library; never rebuild/replace the host GPU.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
if [ -n "${HARMATTAN_PREBUILT_HELPERS:-}" ]; then
    case "${1:-matrices}:$#" in
        matrices:0) helper=matrices ;; --splash:1) helper=splash ;; --handoff:1) helper=handoff ;;
        *) exit 2 ;;
    esac
    exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/prebuilt-helpers.py" "$helper"
fi
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
out="$work_root/compositor-guest"
link_root="$out/link-inputs"
variant=matrices
if [ "$#" -eq 1 ] && [ "$1" = --splash ]; then
    variant=splash
    set -- "$repo_root/scripts/harmattan-qemu/compositor-splash-guest.c"
elif [ "$#" -eq 1 ] && [ "$1" = --handoff ]; then
    variant=handoff
    set -- "$repo_root/scripts/harmattan-qemu/compositor-handoff-guest.c" \
        "$repo_root/scripts/harmattan-qemu/compositor-input-handoff-guest.c"
else
    test "$#" -eq 0 || exit 2
fi
mkdir -p "$link_root"
rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
check_sha() {
    test "$(shasum -a 256 "$1" | cut -d ' ' -f 1)" = "$2" || {
        echo "Compositor build input hash mismatch, retained: $1" >&2; exit 1;
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
extract_input libc.so.6 /lib/libc-2.10.1.so 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
extract_input libdl.so.2 /lib/libdl-2.10.1.so 46e89f3e896c176377ee1aca99ce27a33cc6dc3820ed6235403ed0fefe234149
# Verify the ABI owner even though it is resolved at runtime, not linked here.
extract_input libmcompositor.so.1.1.3 /usr/lib/libmcompositor.so.1.1.3 e9fcdb50530076abce62aaae65f5116a71badc283c89111a0d5e38f13b4a8c1b
gles="$repo_root/extracted/pr1.0-qemu-adaptation/usr/lib/libGLESv2.so.1.4.9"
check_sha "$gles" f8d9e4931b395581259766876532c311d2d6d518edc0b48ba2d93744a7fd887e
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fPIC -shared -O2 -Wall -Wextra -Werror \
    -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined,-z,max-page-size=4096 \
    -Wl,-soname,n00-compositor-matrices.so \
    "$repo_root/scripts/harmattan-qemu/compositor-matrices-guest.c" \
    "$repo_root/scripts/harmattan-qemu/compositor-restacker-guest.c" \
    "$repo_root/scripts/harmattan-qemu/compositor-pixmap-guest.c" \
    "$@" \
    "$link_root/libdl.so.2" "$link_root/libc.so.6" "$gles" \
    -o "$out/n00-compositor-$variant.so"
file "$out/n00-compositor-$variant.so"
shasum -a 256 "$out/n00-compositor-$variant.so"
