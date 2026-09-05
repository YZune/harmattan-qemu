#!/bin/sh
# Native Cocoa presentation; always a private snapshot, never the old launcher.
set -eu
umask 077
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
python_bin=${HARMATTAN_PYTHON:-python3}
kernel=${HARMATTAN_KERNEL:-"$repo_root/extracted/pr1.0-qemu-adaptation/zImage-2.6.32.26-qemu"}
raw=${HARMATTAN_GUEST_IMAGE:-"$repo_root/extracted/hybrid-pr1.3-qemu/arm-qemu-rm680-image-pr1.3-ui.raw"}
mode=${1:-interactive}
network=${HARMATTAN_UI_NETWORK:-off}
if [ "$mode" = --network-diagnostic ]; then network=user; fi
case "$network" in user|off) ;; *) echo 'HARMATTAN_UI_NETWORK must be user or off.' >&2; exit 2 ;; esac
case "$mode" in
    interactive|--network-diagnostic|--usability-diagnostic|--usability-headless-diagnostic|--smoke|--serial-smoke|--headless-smoke|--display-smoke|--input-smoke|--landscape-smoke|--calculator-diagnostic|--calculator-headless-diagnostic|--orientation-diagnostic|--orientation-headless-diagnostic|--gpu-diagnostic|--gpu-headless-diagnostic|--animation-diagnostic|--animation-headless-diagnostic|--splash-diagnostic|--splash-headless-diagnostic|--handoff-diagnostic|--handoff-headless-diagnostic|--startup-input-diagnostic|--startup-input-headless-diagnostic|--performance-diagnostic|--performance-headless-diagnostic) ;;
    *) echo "Usage: sh $0 [--network-diagnostic|--usability-diagnostic|--usability-headless-diagnostic|--smoke|--serial-smoke|--headless-smoke|--display-smoke|--input-smoke|--landscape-smoke|--calculator-diagnostic|--calculator-headless-diagnostic|--orientation-diagnostic|--orientation-headless-diagnostic|--gpu-diagnostic|--gpu-headless-diagnostic|--animation-diagnostic|--animation-headless-diagnostic|--splash-diagnostic|--splash-headless-diagnostic|--handoff-diagnostic|--handoff-headless-diagnostic|--startup-input-diagnostic|--startup-input-headless-diagnostic|--performance-diagnostic|--performance-headless-diagnostic]" >&2; exit 2 ;;
esac
test "$#" -le 1 || exit 2
# Existing diagnostics retain their historical build/idle defaults. Normal use
# and the combined regression share the verified idle/input-capable build.
runtime=${HARMATTAN_UI_RUNTIME:-}
if [ -z "$runtime" ]; then
    case "$mode" in interactive|--network-diagnostic|--usability-diagnostic|--usability-headless-diagnostic) runtime=responsive ;; *) runtime=legacy ;; esac
fi
case "$runtime" in
    responsive) default_bin="$work_root/qemu-9.1.3-interaction/build-arm64-interaction"; default_idle=wfi ;;
    legacy) default_bin="$work_root/qemu-9.1.3/build-arm64-cocoa"; default_idle=spin ;;
    *) echo 'HARMATTAN_UI_RUNTIME must be responsive or legacy' >&2; exit 2 ;;
esac
bin_root=${HARMATTAN_UI_BUILD_ROOT:-"$default_bin"}
skin=${HARMATTAN_UI_SKIN:-}
if [ -z "$skin" ]; then
    skin=off
    # Artwork is user-supplied and opt-in in the public source distribution.
fi
case "$skin" in black|frame|off) ;; *) echo 'HARMATTAN_UI_SKIN must be black, frame or off' >&2; exit 2 ;; esac
N00_COCOA_N9_SKIN=$skin
export N00_COCOA_N9_SKIN
keyboard=${HARMATTAN_UI_KEYBOARD:-}
if [ -z "$keyboard" ]; then
    case "$mode" in interactive|--usability-diagnostic|--usability-headless-diagnostic) keyboard=on ;; *) keyboard=off ;; esac
fi
case "$keyboard" in on|off) ;; *) echo 'HARMATTAN_UI_KEYBOARD must be on or off' >&2; exit 2 ;; esac
animations=${HARMATTAN_UI_ANIMATIONS:-on}
case "$animations" in on|off) ;; *) echo 'HARMATTAN_UI_ANIMATIONS must be on or off' >&2; exit 2 ;; esac
splash=${HARMATTAN_UI_SPLASH:-off}
case "$splash" in on|off) ;; *) echo 'HARMATTAN_UI_SPLASH must be on or off' >&2; exit 2 ;; esac
boot_animation=${HARMATTAN_UI_BOOT_ANIMATION:-on}
case "$boot_animation" in on|off) ;; *) echo 'HARMATTAN_UI_BOOT_ANIMATION must be on or off' >&2; exit 2 ;; esac
default_handoff=off
if [ "$mode" = interactive ] && [ "$animations" = on ] && [ "$splash" = off ]; then default_handoff=on; fi
handoff=${HARMATTAN_UI_HANDOFF:-$default_handoff}
case "$handoff" in on|off) ;; *) echo 'HARMATTAN_UI_HANDOFF must be on or off' >&2; exit 2 ;; esac
clock=${HARMATTAN_UI_CLOCK:-}
if [ -z "$clock" ]; then
    case "$mode" in
        interactive|--usability-diagnostic|--usability-headless-diagnostic|--gpu-diagnostic|--gpu-headless-diagnostic|--animation-diagnostic|--animation-headless-diagnostic|--splash-diagnostic|--splash-headless-diagnostic|--handoff-diagnostic|--handoff-headless-diagnostic|--startup-input-diagnostic|--startup-input-headless-diagnostic) clock=host ;;
        *) clock=off ;;
    esac
fi
case "$clock" in host|off) ;; *) echo 'HARMATTAN_UI_CLOCK must be host or off' >&2; exit 2 ;; esac
if [ "$mode" = interactive ] && [ "$handoff" = on ] && { [ "$animations" != on ] || [ "$splash" != off ]; }; then
    echo 'Display handoff currently requires animations on and splash off.' >&2; exit 2
fi
# Override only for rotation regression; the UI default is upright Home.
rotation=${HARMATTAN_UI_ROTATION:-270}
case "$rotation" in 0|90|180|270) ;; *) echo 'Invalid rotation' >&2; exit 2 ;; esac
idle=${HARMATTAN_UI_IDLE:-$default_idle}
case "$idle" in
    spin) idle_arg=nohlt ;;
    wfi) idle_arg=hlt ;;
    *) echo 'HARMATTAN_UI_IDLE must be spin or wfi' >&2; exit 2 ;;
esac
HARMATTAN_UI_IDLE_PROFILE=$idle
export HARMATTAN_UI_IDLE_PROFILE
profile=${HARMATTAN_UI_PROFILE:-0}
case "$profile:$mode" in
    0:*) ;;
    1:--performance-diagnostic|1:--performance-headless-diagnostic) ;;
    *) echo 'HARMATTAN_UI_PROFILE=1 is only supported by performance diagnostics.' >&2; exit 2 ;;
esac
HARMATTAN_UI_PROFILE=$profile
export HARMATTAN_UI_PROFILE
scanout_probe=${HARMATTAN_UI_SCANOUT_PROBE:-0}
case "$scanout_probe:$profile:$mode" in
    0:*) ;;
    1:1:--performance-diagnostic|1:1:--performance-headless-diagnostic) ;;
    *) echo 'Scanout probes require trace-enabled performance diagnostics.' >&2; exit 2 ;;
esac
activity_probe=${HARMATTAN_UI_ACTIVITY_PROBE:-0}
case "$activity_probe:$scanout_probe:$profile:$mode" in
    0:*)
        test -z "${N00_COCOA_ACTIVITY:-}" || { echo 'Activity settings require the activity diagnostic.' >&2; exit 2; } ;;
    1:1:1:--performance-diagnostic)
        case "${N00_COCOA_ACTIVITY:-}" in 0|1) ;; *) echo 'Select N00_COCOA_ACTIVITY=0 or 1 explicitly.' >&2; exit 2 ;; esac ;;
    *) echo 'Activity probes require bounded trace-enabled Cocoa performance diagnostics.' >&2; exit 2 ;;
esac
interaction_probe=${HARMATTAN_UI_INTERACTION_PROBE:-0}
case "$interaction_probe:$activity_probe:$scanout_probe:$profile:$mode" in
    0:*)
        test -z "${N00_COCOA_INTERACTION:-}" || { echo 'Input activity settings require the interaction diagnostic.' >&2; exit 2; } ;;
    1:1:1:1:--performance-diagnostic)
        test "${N00_COCOA_ACTIVITY:-}" = 0 || { echo 'Whole-run activity must be off for the interaction diagnostic.' >&2; exit 2; }
        case "${N00_COCOA_INTERACTION:-}" in 0|1) ;; *) echo 'Select N00_COCOA_INTERACTION=0 or 1 explicitly.' >&2; exit 2 ;; esac ;;
    *) echo 'Input activity requires bounded trace-enabled Cocoa performance diagnostics.' >&2; exit 2 ;;
esac
input_activity=${HARMATTAN_UI_INPUT_ACTIVITY:-on}
case "$input_activity" in on|off) ;; *) echo 'HARMATTAN_UI_INPUT_ACTIVITY must be on or off' >&2; exit 2 ;; esac
runtime_activity=0
case "$runtime:$mode" in
    responsive:interactive|responsive:--usability-diagnostic)
        if [ "$input_activity" = on ]; then runtime_activity=1; fi
        N00_COCOA_ACTIVITY=0
        N00_COCOA_INTERACTION=$runtime_activity
        export N00_COCOA_ACTIVITY N00_COCOA_INTERACTION
        ;;
esac
display=cocoa,zoom-to-fit=on
case "$mode" in
    # The touch-only guest has no pointer to replace Cocoa's hidden host cursor.
    interactive) display="$display,show-cursor=on" ;;
    --network-diagnostic|--usability-headless-diagnostic|--serial-smoke|--headless-smoke|--display-smoke|--input-smoke|--landscape-smoke|--calculator-headless-diagnostic|--orientation-headless-diagnostic|--gpu-headless-diagnostic|--animation-headless-diagnostic|--splash-headless-diagnostic|--handoff-headless-diagnostic|--startup-input-headless-diagnostic|--performance-headless-diagnostic) display=none ;;
esac
if [ "$mode" = --landscape-smoke ]; then rotation=0; fi
if [ "$display" = none ]; then N00_COCOA_N9_SKIN=off; fi
build_options="$bin_root/meson-info/intro-buildoptions.json"
if [ -n "${HARMATTAN_APP_CONTENTS:-}" ]; then
    test "$runtime" = responsive || { echo 'The release contains only the responsive runtime.' >&2; exit 2; }
    bin_root="$HARMATTAN_APP_CONTENTS/MacOS"
    dgles_runtime="$HARMATTAN_APP_CONTENTS/Frameworks"
else
if [ ! -f "$build_options" ]; then
    build_mode=--cocoa
    if [ "$runtime" = responsive ]; then build_mode=--cocoa-interaction; fi
    echo "Missing $build_options; run build-arm64-port.sh $build_mode first." >&2
    exit 1
fi
# Use the libraries selected at build time, not a different legacy directory
# that happens to exist. No third-party Python dependency is required.
dgles_root=$("$python_bin" -c 'import json,sys; print(next(x["value"] for x in json.load(open(sys.argv[1])) if x["name"] == "n00_dgles_dir"))' "$build_options")
if [ -n "${HARMATTAN_DGLES_ROOT:-}" ] && [ "$HARMATTAN_DGLES_ROOT" != "$dgles_root" ]; then
    echo 'DGLES override differs from this Cocoa build; rebuild with that path first.' >&2
    exit 1
fi
test -n "$dgles_root" || { echo 'This Cocoa build has no DGLES support.' >&2; exit 1; }
dgles_runtime="$dgles_root/objs-arm64"
fi
for required in "$bin_root/qemu-system-arm" "$bin_root/qemu-img" "$kernel" "$raw" "$dgles_runtime/libEGL.1.dylib"; do
    test -f "$required" || { echo "Missing runtime file: $required" >&2; exit 1; }
done
file "$bin_root/qemu-system-arm" | grep -q 'Mach-O 64-bit executable arm64' || exit 1
DYLD_LIBRARY_PATH="$dgles_runtime${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
HARMATTAN_DGLES_RUNTIME_DIR="$dgles_runtime"
export DYLD_LIBRARY_PATH HARMATTAN_DGLES_RUNTIME_DIR
if [ "$runtime" = responsive ]; then
    "$bin_root/qemu-system-arm" -trace help 2>&1 | grep -q '^n00_lease_config$' || {
        echo 'Responsive runtime requires build-arm64-port.sh --cocoa-interaction (or select HARMATTAN_UI_RUNTIME=legacy).' >&2; exit 1;
    }
fi
qemu_binary="$bin_root/qemu-system-arm"
if [ "$network" = user ]; then
    strings "$qemu_binary" | grep -q n00-smc91c111-window || {
        echo 'Networking requires a fresh native build with the N00 network patch.' >&2; exit 1;
    }
fi
if [ "$mode" = interactive ] && [ "$boot_animation" = on ]; then
    strings "$qemu_binary" | grep -q N00_COCOA_BOOT_ANIMATION || {
        echo 'Boot animation requires a fresh --cocoa-interaction build (or HARMATTAN_UI_BOOT_ANIMATION=off).' >&2; exit 1;
    }
fi
if [ "$N00_COCOA_N9_SKIN" = black ]; then
    strings "$bin_root/qemu-system-arm" | grep -q N00_COCOA_N9_SKIN || {
        echo 'N9 frame requires rebuilding with build-arm64-port.sh --cocoa-interaction (or use HARMATTAN_UI_SKIN=off).' >&2; exit 1;
    }
    qemu_binary="$bin_root/Harmattan N9.app/Contents/MacOS/qemu-system-arm"
    test -x "$qemu_binary" && test -f "$bin_root/Harmattan N9.app/Contents/Resources/n9-black-livven.png" || {
        echo 'Rebuild the Cocoa interaction runtime to bundle the N9 artwork.' >&2; exit 1;
    }
fi
if [ "$profile" = 1 ]; then
    "$bin_root/qemu-system-arm" -trace help 2>&1 | grep -q '^n00_profile_gles$' || {
        echo 'Profiling requires the independent --cocoa-profile build.' >&2; exit 1;
    }
fi
if [ "$scanout_probe" = 1 ]; then
    "$bin_root/qemu-system-arm" -trace help 2>&1 | grep -q '^n00_scanout_frame$' || {
        echo 'Scanout probes require the separate diagnostic build.' >&2; exit 1;
    }
fi
if [ "$activity_probe" = 1 ]; then
    "$bin_root/qemu-system-arm" -trace help 2>&1 | grep -q '^n00_activity_lifecycle$' || {
        echo 'Activity probes require the independent --cocoa-activity build.' >&2; exit 1;
    }
fi
if [ "$interaction_probe" = 1 ]; then
    "$bin_root/qemu-system-arm" -trace help 2>&1 | grep -q '^n00_lease_config$' || {
        echo 'Input activity requires the independent --cocoa-interaction build.' >&2; exit 1;
    }
fi
qemu_name='Harmattan PR1.3 - ARM64 port'
if [ "$N00_COCOA_N9_SKIN" = black ]; then qemu_name='Nokia N9 - Black - Harmattan PR1.3'; fi
if [ "$N00_COCOA_N9_SKIN" = frame ]; then qemu_name='N9 frame - Harmattan PR1.3'; fi
case "$mode" in
    --usability-diagnostic|--usability-headless-diagnostic) qemu_name="$qemu_name - usability diagnostic" ;;
    --animation-diagnostic|--animation-headless-diagnostic) qemu_name="$qemu_name - animation diagnostic" ;;
    --splash-diagnostic|--splash-headless-diagnostic) qemu_name="$qemu_name - splash diagnostic" ;;
    --handoff-diagnostic|--handoff-headless-diagnostic) qemu_name="$qemu_name - display handoff diagnostic" ;;
    --startup-input-diagnostic|--startup-input-headless-diagnostic) qemu_name="$qemu_name - startup input diagnostic" ;;
esac
if [ -n "${HARMATTAN_UI_THREAD_HELPER:-}" ]; then
    case "$mode" in
        --performance-diagnostic|--performance-headless-diagnostic) ;;
        *) echo 'Thread snapshots require bounded performance diagnostics.' >&2; exit 2 ;;
    esac
    test -x "$HARMATTAN_UI_THREAD_HELPER" || { echo 'Missing thread snapshot helper' >&2; exit 1; }
    qemu_name="$qemu_name,debug-threads=on"
fi
raw_bytes=$(stat -f %z "$raw")
if [ "$raw_bytes" -le 0 ] || [ "$raw_bytes" -gt 34359738368 ]; then
    echo 'Backing must be non-empty and at most 32 GiB; refusing to shrink it.' >&2
    exit 1
fi
run_root=$(mktemp -d "$work_root/run.XXXXXX")
if ! cp -c "$raw" "$run_root/pr13-backing.raw"; then
    echo "APFS clone required; retained $run_root for inspection." >&2
    exit 1
fi
"$bin_root/qemu-img" create -q -f qcow2 -F raw -b "$run_root/pr13-backing.raw" "$run_root/pr13-32g.qcow2" 32G
echo "Native UI run artifacts: $run_root"
set -- "$qemu_binary" -M n00-port-spike \
    -name "$qemu_name" -kernel "$kernel" \
    -append "init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 $idle_arg console=ttyS0,115200n8 omap3_die_id" \
    -drive "if=sd,format=qcow2,file=$run_root/pr13-32g.qcow2" \
    -snapshot -display "$display" -rotate "$rotation" -no-reboot
if [ "$network" = user ]; then
    set -- "$@" -nic user,model=smc91c111,mac=52:54:00:12:34:56
else
    set -- "$@" -nic none
fi
trace_options=
if [ "$profile" = 1 ]; then
    trace_pattern=n00_profile_\*
    if [ "$scanout_probe" = 1 ]; then trace_pattern=n00_\*; fi
    trace_options="enable=$trace_pattern,file=$run_root/profile.log"
fi
if [ "$mode" = --usability-diagnostic ] && [ "$runtime" = responsive ]; then
    trace_options="enable=n00_lease_*,file=$run_root/interaction.log"
fi
if [ -n "$trace_options" ]; then
    set -- "$@" -trace "$trace_options"
fi
case "$mode" in
    --network-diagnostic)
        exec "$python_bin" -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-network.py" \
            --output "$run_root/network" -- "$@" ;;
    --serial-smoke)
        exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-port.py" \
            --log "$run_root/serial.log" -- "$@" -serial stdio -monitor none ;;
    --display-smoke)
        exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-display.py" \
            --output "$run_root/display" --rotation "$rotation" -- "$@" ;;
    --input-smoke)
        exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/smoke-arm64-input.py" \
            --output "$run_root/input" --rotation "$rotation" -- "$@" ;;
    --calculator-diagnostic|--calculator-headless-diagnostic) set -- --exercise-calculator -- "$@" ;;
    --orientation-diagnostic|--orientation-headless-diagnostic) set -- --exercise-orientation --exercise-calculator --timeout 300 -- "$@" ;;
    --gpu-diagnostic|--gpu-headless-diagnostic) set -- --system-ui on --device-orientation display --exercise-calculator --timeout 240 -- "$@" ;;
    --usability-diagnostic|--usability-headless-diagnostic) set -- --system-ui on --device-orientation display --compositor-animations on --splash off --display-handoff on --exercise-keyboard --exercise-transitions --timeout 480 -- "$@" ;;
    --animation-diagnostic|--animation-headless-diagnostic) set -- --system-ui on --device-orientation display --compositor-animations on --exercise-transitions --timeout 300 -- "$@" ;;
    --splash-diagnostic|--splash-headless-diagnostic) set -- --system-ui on --device-orientation display --compositor-animations on --splash on --exercise-transitions --timeout 300 -- "$@" ;;
    --handoff-diagnostic|--handoff-headless-diagnostic) set -- --system-ui on --device-orientation display --compositor-animations on --splash off --display-handoff on --exercise-transitions --timeout 300 -- "$@" ;;
    --startup-input-diagnostic|--startup-input-headless-diagnostic) set -- --system-ui on --device-orientation display --compositor-animations on --splash off --exercise-startup-input --timeout 300 -- "$@" ;;
    --performance-diagnostic|--performance-headless-diagnostic) set -- --measure-performance -- "$@" ;;
    interactive)
        echo 'Host cursor stays visible; Control+Option+G releases QEMU input focus.'
        echo 'Virtual device orientation follows display rotation; no physical sensor calibration.'
        echo 'Original System UI provides the statusbar pixmap; device services are still incomplete.'
        if [ "$clock" = host ]; then echo 'Host UTC and local timezone are synchronized into this disposable guest.'; fi
        echo 'Guest input is held during startup checks; release buttons/keys and wait for READY.'
        if [ "$boot_animation" = on ]; then
            echo 'Original boot movie covers startup; the verified desktop appears when ready.'
        fi
        if [ "$splash" = on ]; then echo 'WARNING: experimental splash visuals and remaining transition flashes are not fully accepted; off is the normal default.'; fi
        if [ "$handoff" = on ]; then echo 'Real-pixel compositor handoff enabled.'; fi
        echo "Runtime: $runtime; CPU idle: $idle; input activity: $runtime_activity; original keyboard: $keyboard."
        if [ "$skin" = black ]; then echo 'Black N9 artwork by Livven: glass supports edge swipes; drag the outer body to move. HARMATTAN_UI_SKIN=off disables it.'; fi
        echo 'Left-button drag scrolls Home.'
        if [ "$keyboard" = on ]; then echo 'Focused text fields use the original on-screen keyboard.'; fi
        echo 'Close QEMU or press Ctrl-C here to exit; all guest writes are discarded.'
        set -- --interactive --compositor-animations "$animations" --splash "$splash" --display-handoff "$handoff" -- "$@"
        if [ "$boot_animation" = on ]; then set -- --boot-animation "$run_root/pr13-backing.raw" "$@"; fi ;;
    *) set -- --verify-input -- "$@" ;;
esac
exec "${HARMATTAN_PYTHON:-python3}" -B "$repo_root/scripts/harmattan-qemu/diagnose-arm64-shell.py" \
    --network "$network" --output "$run_root/ui" --rotation "$rotation" --clock "$clock" --input-method "$keyboard" "$@"
