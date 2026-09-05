#!/bin/sh
# Build tiny ARMEL wire tests, without a Harmattan SDK, sysroot or libc.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
cc=$(command -v "${HARMATTAN_ARMEL_CLANG:-clang}")
wire="$work_root/qemu-9.1.3/hw/arm"
out="$work_root/guest-probes"
test -f "$wire/n00_gles_wire.h"
test -x "$cc"
mkdir -p "$out"
for variant in positive negative; do
    set --
    if [ "$variant" = negative ]; then set -- -DN00_GLES_NEGATIVE; fi
    "$cc" --target=arm-linux-gnueabi -mcpu=cortex-a8 -mfpu=neon \
        -mfloat-abi=softfp -fuse-ld=lld -nostdlib -static -fno-builtin \
        -O2 -Wall -Wextra -Werror -Wl,--build-id=none -I"$wire" "$@" \
        "$repo_root/scripts/harmattan-qemu/probe-armel-gles.S" \
        "$repo_root/scripts/harmattan-qemu/smoke-gles-guest.c" \
        -o "$out/smoke-gles-guest-$variant"
    file "$out/smoke-gles-guest-$variant"
done
for variant in render render-negative; do
    set --
    if [ "$variant" = render-negative ]; then set -- -DN00_RENDER_NEGATIVE; fi
    "$cc" --target=arm-linux-gnueabi -mcpu=cortex-a8 -mfpu=neon \
        -mfloat-abi=softfp -fuse-ld=lld -nostdlib -static -fno-builtin \
        -O2 -Wall -Wextra -Werror -Wl,--build-id=none -I"$wire" "$@" \
        "$repo_root/scripts/harmattan-qemu/probe-armel-gles-render.S" \
        "$repo_root/scripts/harmattan-qemu/smoke-gles-render-guest.c" \
        -o "$out/smoke-gles-guest-$variant"
    file "$out/smoke-gles-guest-$variant"
done
