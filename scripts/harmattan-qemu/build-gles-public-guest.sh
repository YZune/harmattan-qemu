#!/bin/sh
# Link to original ARM guest libraries; never replace libraries inside the image.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
link_root="$work_root/public-api-link-inputs"
adaptation="$repo_root/extracted/pr1.0-qemu-adaptation/usr/lib"
dgles_root=${HARMATTAN_DGLES_ROOT:-"$work_root/dgles2-host/gles-libs-1.4.2/dgles2"}
rootfs=${HARMATTAN_PUBLIC_ROOTFS:-"$repo_root/extracted/hybrid-pr1.3-qemu/pr1.3-rootfs-qemu-rescue.ext4"}
debugfs_bin=${HARMATTAN_DEBUGFS:-debugfs}
out="$work_root/guest-probes"
variant=${1:---public}
if [ "$#" -gt 1 ] || { [ "$variant" != --public ] && [ "$variant" != --shell-api ]; }; then
    echo "Usage: sh $0 [--public|--shell-api]" >&2
    exit 2
fi
probe_name=smoke-gles-public-guest
set --
if [ "$variant" = --shell-api ]; then
    probe_name=smoke-gles-shell-api-guest
    set -- -DN00_SHELL_API_PROBE
fi
for required in "$adaptation/libEGL.so.1.3.0" "$adaptation/libGLESv2.so.1.4.9" \
    "$dgles_root/include/EGL/egl.h" "$dgles_root/include/GLES2/gl2.h"; do
    test -f "$required" || { echo "Missing public API link input: $required" >&2; exit 1; }
done

check_sha() {
    actual=$(shasum -a 256 "$1" | cut -d ' ' -f 1)
    if [ "$actual" != "$2" ]; then
        echo "Pinned guest library SHA-256 mismatch: $1; retained, not overwritten." >&2
        exit 1
    fi
}

extract_input() {
    input_name=$1
    guest_path=$2
    expected=$3
    if [ ! -e "$link_root/$input_name" ]; then
        test -f "$rootfs" || { echo "Missing read-only source rootfs: $rootfs" >&2; exit 1; }
        rootfs=$(CDPATH= cd -- "$(dirname -- "$rootfs")" && pwd)/$(basename -- "$rootfs")
        mkdir -p "$link_root"
        extract_dir=$(mktemp -d "$link_root/.extract.XXXXXX")
        # No -w: debugfs reads the ext4 image without mounting or modifying it.
        # Use fixed relative output names inside a unique directory, not a
        # path interpolated into the debugfs command parser.
        (cd "$extract_dir" && "$debugfs_bin" -R "dump $guest_path $input_name" "$rootfs")
        check_sha "$extract_dir/$input_name" "$expected"
        mv -n "$extract_dir/$input_name" "$link_root/$input_name"
    fi
    check_sha "$link_root/$input_name" "$expected"
}

check_sha "$adaptation/libEGL.so.1.3.0" 105dd15bca74b8d0cf348d4505bd2a05cc4711d444387bd8fc454738c6310b58
check_sha "$adaptation/libGLESv2.so.1.4.9" f8d9e4931b395581259766876532c311d2d6d518edc0b48ba2d93744a7fd887e
extract_input libc.so.6 /lib/libc-2.10.1.so 434c9ee9c201b0a3ae07ca6dbb85430719ed98f984fa75354f2210ce09dac5ae
extract_input libX11.so.6 /usr/lib/libX11.so.6.3.0 4b43c17356976b75b6d05204d03bc4693aa6ffd364dfd499264ebf4760b3b4e0
mkdir -p "$out"
"$cc" --target=arm-linux-gnueabihf -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard \
    -fuse-ld=lld -nostdlib -ffreestanding -fno-builtin -fno-pie -O2 -Wall -Wextra -Werror "$@" \
    -I"$dgles_root/include" -Wl,--build-id=none,--hash-style=sysv,--allow-shlib-undefined \
    -Wl,-no-pie,--dynamic-linker=/lib/ld-linux.so.3,-z,max-page-size=4096 \
    "$repo_root/scripts/harmattan-qemu/start-armel-libc.S" \
    "$repo_root/scripts/harmattan-qemu/smoke-gles-public-guest.c" \
    "$adaptation/libEGL.so.1.3.0" "$adaptation/libGLESv2.so.1.4.9" \
    "$link_root/libX11.so.6" "$link_root/libc.so.6" \
    -o "$out/$probe_name"
file "$out/$probe_name"
