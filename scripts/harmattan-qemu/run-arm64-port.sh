#!/bin/sh
# Disposable headless experiment. The existing UI launcher is unchanged.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
bin_root="$work_root/qemu-9.1.3/build-arm64-headless"
kernel="$repo_root/extracted/pr1.0-qemu-adaptation/zImage-2.6.32.26-qemu"
raw="$repo_root/extracted/hybrid-pr1.3-qemu/arm-qemu-rm680-image-pr1.3-ui.raw"
mode=${1:-interactive}
if [ "$#" -gt 1 ] || { [ "$mode" != interactive ] && [ "$mode" != --smoke ] && [ "$mode" != --display-smoke ] && [ "$mode" != --gles-smoke ] && [ "$mode" != --gles-negative ] && [ "$mode" != --gles-render-smoke ] && [ "$mode" != --gles-render-negative ] && [ "$mode" != --xorg-smoke ] && [ "$mode" != --public-shm-smoke ] && [ "$mode" != --public-image-smoke ] && [ "$mode" != --public-shell-api-smoke ] && [ "$mode" != --shell-diagnostic ] && [ "$mode" != --shell-smoke ] && [ "$mode" != --input-smoke ] && [ "$mode" != --shell-input-diagnostic ] && [ "$mode" != --shell-input-smoke ]; }; then
    echo "Usage: sh $0 [--smoke|--display-smoke|--gles-smoke|--gles-negative|--gles-render-smoke|--gles-render-negative|--xorg-smoke|--public-shm-smoke|--public-image-smoke|--public-shell-api-smoke|--shell-diagnostic|--shell-smoke|--input-smoke|--shell-input-diagnostic|--shell-input-smoke]" >&2
    exit 2
fi
if [ "${mode#--gles-}" != "$mode" ] || [ "$mode" = --xorg-smoke ] || [ "${mode#--public-}" != "$mode" ] || [ "${mode#--shell-}" != "$mode" ] || [ "$mode" = --input-smoke ]; then
    bin_root="$work_root/qemu-9.1.3/build-arm64-gles"
    dgles_root=${HARMATTAN_DGLES_ROOT:-"$work_root/dgles2-host/gles-libs-1.4.2/dgles2"}
    test -f "$dgles_root/objs-arm64/libEGL.dylib" || { echo 'Build the DGLES host libraries first.' >&2; exit 1; }
    DYLD_LIBRARY_PATH="$dgles_root/objs-arm64${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
    export DYLD_LIBRARY_PATH
fi
if [ "${mode#--public-}" != "$mode" ]; then
    probe="$work_root/guest-probes/smoke-gles-public-guest"
    if [ "$mode" = --public-shell-api-smoke ]; then probe="$work_root/guest-probes/smoke-gles-shell-api-guest"; fi
    test -f "$probe" || { echo 'Run build-gles-public-guest.sh first.' >&2; exit 1; }
fi
if [ "${mode#--gles-}" != "$mode" ]; then
    variant=positive
    if [ "$mode" = --gles-negative ]; then variant=negative; fi
    if [ "$mode" = --gles-render-smoke ]; then variant=render; fi
    if [ "$mode" = --gles-render-negative ]; then variant=render-negative; fi
    probe="$work_root/guest-probes/smoke-gles-guest-$variant"
    test -f "$probe" || { echo 'Run build-gles-guest.sh first.' >&2; exit 1; }
fi
for required in "$bin_root/qemu-system-arm" "$bin_root/qemu-img" "$kernel" "$raw"; do
    if [ ! -f "$required" ]; then
        echo "Missing runtime file: $required" >&2
        exit 1
    fi
done
if ! file "$bin_root/qemu-system-arm" | grep -q 'Mach-O 64-bit executable arm64'; then
    echo 'Expected the native arm64 experimental QEMU binary.' >&2
    exit 1
fi
raw_bytes=$(stat -f %z "$raw")
if [ "$raw_bytes" -gt 34359738368 ] || [ "$raw_bytes" -le 0 ]; then
    echo 'The backing image must be non-empty and at most 32 GiB; refusing to shrink it.' >&2
    exit 1
fi
run_root=$(mktemp -d "$work_root/run.XXXXXX")
image="$run_root/pr13-32g.qcow2"
backing="$run_root/pr13-backing.raw"

# Modern eMMC requires a power-of-two capacity. Pad virtually, never resize
# the original 30 GiB raw image. Freeze a private APFS clone first, so another
# emulator cannot change this run's backing file after startup. Prefer closing
# the old emulator first for an orderly guest filesystem checkpoint.
if ! cp -c "$raw" "$backing"; then
    echo "APFS clone failed. Use an APFS HARMATTAN_PORT_WORKSPACE; artifacts retained in $run_root." >&2
    exit 1
fi
"$bin_root/qemu-img" create -q -f qcow2 -F raw -b "$backing" "$image" 32G
# All guest writes go to QEMU's disposable -snapshot on top of this clone.
echo "Run artifacts: $run_root"
set -- "$bin_root/qemu-system-arm" -M n00-port-spike \
    -kernel "$kernel" \
    -append 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 nohlt console=ttyS0,115200n8 omap3_die_id' \
    -drive "if=sd,format=qcow2,file=$image" \
    -snapshot -display none -no-reboot

if [ "${mode#--gles-}" != "$mode" ]; then
    set -- -- "$@"
    if [ "$mode" = --gles-negative ] || [ "$mode" = --gles-render-negative ]; then set -- --negative "$@"; fi
    if [ "$mode" = --gles-render-smoke ] || [ "$mode" = --gles-render-negative ]; then set -- --render "$@"; fi
    exec "${HARMATTAN_PYTHON:-python3}" \
        -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-gles.py" \
        --output "$run_root/gles" --probe "$probe" "$@"
elif [ "${mode#--public-}" != "$mode" ]; then
    noxshm=0
    if [ "$mode" = --public-image-smoke ]; then noxshm=1; fi
    set -- -- "$@"
    if [ "$mode" = --public-shell-api-smoke ]; then set -- --shell-api "$@"; fi
    exec "${HARMATTAN_PYTHON:-python3}" \
        -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-gles-public.py" \
        --output "$run_root/public" --probe "$probe" --noxshm "$noxshm" "$@"
elif [ "${mode#--shell-}" != "$mode" ]; then
    set -- -- "$@"
    if [ "$mode" = --shell-smoke ]; then set -- --verify-desktop "$@"; fi
    if [ "$mode" = --shell-input-diagnostic ]; then set -- --exercise-input "$@"; fi
    if [ "$mode" = --shell-input-smoke ]; then set -- --verify-input "$@"; fi
    exec "${HARMATTAN_PYTHON:-python3}" \
        -B "$repo_root/scripts/harmattan-qemu/diagnose-arm64-shell.py" \
        --output "$run_root/shell" "$@"
elif [ "$mode" = --input-smoke ]; then
    exec "${HARMATTAN_PYTHON:-python3}" \
        -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-input.py" \
        --output "$run_root/input" -- "$@"
elif [ "$mode" = --xorg-smoke ]; then
    exec "${HARMATTAN_PYTHON:-python3}" \
        -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-xorg.py" \
        --output "$run_root/xorg" -- "$@"
elif [ "$mode" = --display-smoke ]; then
    exec "${HARMATTAN_PYTHON:-python3}" \
        "$repo_root/scripts/harmattan-qemu/smoke-arm64-display.py" \
        --output "$run_root" -- "$@"
elif [ "$mode" = --smoke ]; then
    exec "${HARMATTAN_PYTHON:-python3}" \
        "$repo_root/scripts/harmattan-qemu/smoke-arm64-port.py" \
        --log "$run_root/serial.log" -- "$@" -serial stdio -monitor none
fi
echo 'Headless serial experiment with framebuffer; no UI shell or speed guarantee.'
echo 'Exit with Ctrl-A then X. Writes are discarded; this run directory is retained.'
exec "$@" \
    -chardev "stdio,id=console,mux=on,logfile=$run_root/serial.log" \
    -serial chardev:console -mon chardev=console,mode=readline
