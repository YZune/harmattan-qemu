#!/bin/sh
# Build the isolated QEMU 9.1.3 N00 direct-boot experiment on Apple Silicon.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
port_root="$repo_root/ports/qemu-n00"
work_root=${HARMATTAN_PORT_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port"}
archive=${HARMATTAN_QEMU_TARBALL:-"$repo_root/downloads/tools/qemu-9.1.3.tar.xz"}
python_bin=${HARMATTAN_PYTHON:-python3}
ninja_bin=${HARMATTAN_NINJA:-ninja}
jobs=${HARMATTAN_BUILD_JOBS:-8}
mode=${1:---headless}
if [ "$#" -gt 1 ] || { [ "$mode" != --headless ] && [ "$mode" != --gles ] && [ "$mode" != --cocoa ] && [ "$mode" != --cocoa-idle ] && [ "$mode" != --cocoa-profile ] && [ "$mode" != --cocoa-scanout ] && [ "$mode" != --cocoa-activity ] && [ "$mode" != --cocoa-interaction ]; }; then
    echo "Usage: sh $0 [--headless|--gles|--cocoa|--cocoa-idle|--cocoa-profile|--cocoa-scanout|--cocoa-activity|--cocoa-interaction]" >&2
    exit 2
fi

# Meson regeneration also locates Ninja on PATH. Resolve the selected
# executable once so it cannot fall back to a broken depot_tools wrapper.
ninja_bin=$(command -v "$ninja_bin")
PATH="$(dirname -- "$ninja_bin"):$PATH"
export PATH

if [ "$(uname -s):$(uname -m)" != Darwin:arm64 ]; then
    echo 'Run this build from a native arm64 macOS shell, not Rosetta.' >&2
    exit 1
fi
if [ ! -f "$archive" ]; then
    echo "Missing QEMU archive: $archive" >&2
    echo 'Download https://download.qemu.org/qemu-9.1.3.tar.xz or set HARMATTAN_QEMU_TARBALL.' >&2
    exit 1
fi
actual_sha=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
if [ "$actual_sha" != 480a77a0ed13a9b39415f639aa020b4eb0d7cc5a52569510dfd830b3af1bac89 ]; then
    echo 'QEMU archive SHA-256 mismatch; refusing to extract or patch.' >&2
    exit 1
fi
"$python_bin" --version
"$ninja_bin" --version
pkg-config --exists glib-2.0 pixman-1 slirp
mkdir -p "$work_root"
work_root=$(CDPATH= cd -- "$work_root" && pwd)
source_root="$work_root/qemu-9.1.3"
if [ "$mode" = --cocoa-idle ]; then source_root="$work_root/qemu-9.1.3-idle"; fi
if [ "$mode" = --cocoa-profile ]; then source_root="$work_root/qemu-9.1.3-profile"; fi
if [ "$mode" = --cocoa-scanout ]; then source_root="$work_root/qemu-9.1.3-scanout"; fi
if [ "$mode" = --cocoa-activity ]; then source_root="$work_root/qemu-9.1.3-activity"; fi
if [ "$mode" = --cocoa-interaction ]; then source_root="$work_root/qemu-9.1.3-interaction"; fi
if [ ! -d "$source_root" ]; then
    mkdir -p "$source_root"
    tar -xf "$archive" --strip-components=1 -C "$source_root"
fi

# The complete release source kit preserves this otherwise network-fetched
# Meson subproject, exported from the exact revision in QEMU's dtc.wrap.
dtc_archive=${HARMATTAN_DTC_TARBALL:-"$repo_root/downloads/tools/qemu-dtc-b6910bec.tar"}
if [ -f "$dtc_archive" ] && [ ! -f "$source_root/subprojects/dtc/meson.build" ]; then
    test "$(shasum -a 256 "$dtc_archive" | cut -d ' ' -f 1)" = 9e37560fd55be30d991118ba8dad60c5c0cb924227cb2671a7543bd6dec3d547 || {
        echo 'Pinned DTC source archive SHA-256 mismatch.' >&2; exit 1;
    }
    tar -xf "$dtc_archive" -C "$source_root/subprojects"
fi

# Do not let git discover the parent Harmattan repository. These paths are
# relative to the generated, standalone QEMU source tree, not this checkout.
(
    cd "$source_root"
    export GIT_CEILING_DIRECTORIES="$work_root"
    base_patch="$port_root/qemu-9.1.3-n00.patch"
    display_patch="$port_root/qemu-9.1.3-n00-display.patch"
    gles_patch="$port_root/qemu-9.1.3-n00-gles.patch"
    render_patch="$port_root/qemu-9.1.3-n00-gles-render.patch"
    public_patch="$port_root/qemu-9.1.3-n00-gles-public.patch"
    shell_patch="$port_root/qemu-9.1.3-n00-gles-shell.patch"
    input_patch="$port_root/qemu-9.1.3-n00-input.patch"
    portrait_patch="$port_root/qemu-9.1.3-n00-portrait.patch"
    idle_patch="$port_root/qemu-9.1.3-n00-idle.patch"
    profile_patch="$port_root/qemu-9.1.3-n00-profile.patch"
    scanout_patch="$port_root/qemu-9.1.3-n00-scanout-probe.patch"
    activity_patch="$port_root/qemu-9.1.3-n00-activity-probe.patch"
    interaction_patch="$port_root/qemu-9.1.3-n00-interaction-activity.patch"
    skin_patch="$port_root/qemu-9.1.3-n00-n9-skin.patch"
    shutdown_patch="$port_root/qemu-9.1.3-n00-cocoa-shutdown.patch"
    frame_patch="$port_root/qemu-9.1.3-n00-n9-frame.patch"
    boot_patch="$port_root/qemu-9.1.3-n00-boot-animation.patch"
    network_patch="$port_root/qemu-9.1.3-n00-network.patch"
    storage_patch="$port_root/qemu-9.1.3-n00-storage-shutdown.patch"

    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$storage_patch" >/dev/null 2>&1; then
        git apply --reverse "$storage_patch"
    fi

    if git apply --reverse --check "$network_patch" >/dev/null 2>&1; then
        git apply --reverse "$network_patch"
    fi

    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$boot_patch" >/dev/null 2>&1; then
        git apply --reverse "$boot_patch"
    fi
    # Unwind the newest recognized increment before checking earlier ones.
    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$frame_patch" >/dev/null 2>&1; then
        git apply --reverse "$frame_patch"
    fi
    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$shutdown_patch" >/dev/null 2>&1; then
        git apply --reverse "$shutdown_patch"
    fi
    # The skin replaces the older absolute-mouse conversion. Remove only an
    # exactly recognized skin increment before checking the historical chain,
    # then reapply it below; a changed/unknown hunk is never discarded.
    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$skin_patch" >/dev/null 2>&1; then
        git apply --reverse "$skin_patch"
    fi
    have_interaction=0
    if [ "$mode" = --cocoa-interaction ] && git apply --reverse --check "$interaction_patch" >/dev/null 2>&1; then
        have_interaction=1
    fi
    have_scanout=0
    # Profiling overlaps the portrait hunk in the DSS renderer. Recognize
    # that final state before checking the earlier, now superseded hunk.
    if { [ "$mode" = --cocoa-scanout ] || [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; } && \
       git apply --reverse --check "$scanout_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$idle_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --include=hw/arm/n00_gles_port.c "$profile_patch" >/dev/null 2>&1; then
        have_scanout=1
        echo 'Independent scanout diagnostic increment already applied.'
    elif { [ "$mode" = --cocoa-profile ] || [ "$mode" = --cocoa-scanout ] || [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; } && \
       git apply --reverse --check "$profile_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$idle_patch" >/dev/null 2>&1; then
        echo 'N00 idle and profiling increments already applied.'
    else
    # The shell increment changes all three render-patch files. Its reverse
    # check covers their new hunks; earlier independent wire/board files are
    # checked below. A clean archive is the reference for full source equality.
    if git apply --reverse --check "$portrait_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$input_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$shell_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$public_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           --exclude=hw/arm/n00_port_spike.c --exclude=hw/arm/meson.build \
           "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_dss_port.c \
           --exclude=hw/arm/n00_port_spike.c --exclude=hw/arm/meson.build \
           "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        echo 'All eight N00 patches already applied; GLES/Cocoa remain opt-in.'
    elif git apply --reverse --check "$input_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$shell_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$public_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           --exclude=hw/arm/n00_port_spike.c --exclude=hw/arm/meson.build \
           "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        echo 'All seven N00 patches already applied; GLES remains opt-in.'
    elif git apply --reverse --check "$shell_patch" >/dev/null 2>&1 && \
       git apply --reverse --check "$public_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        echo 'All six N00 patches already applied; GLES remains opt-in.'
    elif git apply --reverse --check "$public_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           "$render_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        git apply --check "$shell_patch"
        git apply "$shell_patch"
    elif git apply --reverse --check "$render_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_gles_port.c \
           "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        git apply --check "$public_patch"
        git apply "$public_patch"
        git apply --check "$shell_patch"
        git apply "$shell_patch"
    elif git apply --reverse --check "$gles_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$display_patch" >/dev/null 2>&1 && \
       git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
           --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        git apply --check "$render_patch"
        git apply "$render_patch"
        git apply --check "$public_patch"
        git apply "$public_patch"
        git apply --check "$shell_patch"
        git apply "$shell_patch"
    elif git apply --reverse --check "$display_patch" >/dev/null 2>&1 && \
         git apply --reverse --check --exclude=hw/arm/n00_port_spike.c \
             --exclude=hw/arm/meson.build "$base_patch" >/dev/null 2>&1; then
        git apply --check "$gles_patch"
        git apply "$gles_patch"
        git apply --check "$render_patch"
        git apply "$render_patch"
        git apply --check "$public_patch"
        git apply "$public_patch"
        git apply --check "$shell_patch"
        git apply "$shell_patch"
    else
        # git apply --check does not model dependencies between patch files.
        # Check/apply one at a time; a failed later step leaves the earlier
        # successful step in place, ready for inspection, never auto-reverted.
        for patch_file in "$base_patch" "$display_patch" "$gles_patch" "$render_patch" "$public_patch" "$shell_patch"; do
            if git apply --reverse --check "$patch_file" >/dev/null 2>&1; then
                continue
            fi
            if ! git apply --check "$patch_file"; then
                echo 'Source differs from this patch step; retained for inspection. Use a fresh HARMATTAN_PORT_WORKSPACE.' >&2
                exit 1
            fi
            git apply "$patch_file"
        done
    fi
    if ! git apply --reverse --check "$input_patch" >/dev/null 2>&1; then
        git apply --check "$input_patch"
        git apply "$input_patch"
    fi
    if ! git apply --reverse --check "$portrait_patch" >/dev/null 2>&1; then
        git apply --check "$portrait_patch"
        git apply "$portrait_patch"
    fi
    fi
    if [ "$mode" = --cocoa-idle ] || [ "$mode" = --cocoa-profile ] || [ "$mode" = --cocoa-scanout ] || [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; then
        if ! git apply --reverse --check "$idle_patch" >/dev/null 2>&1; then
            git apply --check "$idle_patch"
            git apply "$idle_patch"
        fi
    fi
    if { [ "$mode" = --cocoa-profile ] || [ "$mode" = --cocoa-scanout ] || [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; } && [ "$have_scanout" = 0 ]; then
        if ! git apply --reverse --check "$profile_patch" >/dev/null 2>&1; then
            git apply --check "$profile_patch"
            git apply "$profile_patch"
        fi
    fi
    if { [ "$mode" = --cocoa-scanout ] || [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; } && [ "$have_scanout" = 0 ]; then
        git apply --check "$scanout_patch"
        git apply "$scanout_patch"
    fi
    if { [ "$mode" = --cocoa-activity ] || [ "$mode" = --cocoa-interaction ]; } && [ "$have_interaction" = 0 ] && ! git apply --reverse --check "$activity_patch" >/dev/null 2>&1; then
        git apply --check "$activity_patch"
        git apply "$activity_patch"
    fi
    if [ "$mode" = --cocoa-interaction ] && [ "$have_interaction" = 0 ]; then
        git apply --check "$interaction_patch"
        git apply "$interaction_patch"
    fi
    if [ "$mode" = --cocoa-interaction ]; then
        if ! git apply --reverse --check "$skin_patch" >/dev/null 2>&1; then
            git apply --check "$skin_patch"
            git apply "$skin_patch"
        fi
        cp "$port_root/n00-n9-skin.h" ui/n00-n9-skin.h
        git apply --check "$shutdown_patch"
        git apply "$shutdown_patch"
        git apply --check "$frame_patch"
        git apply "$frame_patch"
        git apply --check "$boot_patch"
        git apply "$boot_patch"
        cp "$port_root/n00-boot-animation.h" ui/n00-boot-animation.h
    fi
    git apply --check "$network_patch"
    git apply "$network_patch"
    if [ "$mode" = --cocoa-interaction ]; then
        git apply --check "$storage_patch"
        git apply "$storage_patch"
        cp "$port_root/n00-storage-shutdown.h" ui/n00-storage-shutdown.h
    fi
)

build_name=build-arm64-headless
display_flag=--disable-cocoa
set --
if [ "$mode" != --headless ]; then
    dgles_root=${HARMATTAN_DGLES_ROOT:-"$work_root/dgles2-host/gles-libs-1.4.2/dgles2"}
    for required in include/EGL/egl.h objs-arm64/libEGL.dylib \
        objs-arm64/libGLES_CM.dylib objs-arm64/libGLESv2.dylib; do
        test -f "$dgles_root/$required" || { echo "Missing DGLES file: $dgles_root/$required" >&2; exit 1; }
    done
    dgles_root=$(CDPATH= cd -- "$dgles_root" && pwd)
    build_name=build-arm64-gles
    if [ "$mode" = --cocoa ]; then
        build_name=build-arm64-cocoa
        display_flag=--enable-cocoa
    fi
    if [ "$mode" = --cocoa-idle ]; then
        build_name=build-arm64-idle
        display_flag=--enable-cocoa
    fi
    if [ "$mode" = --cocoa-profile ]; then
        build_name=build-arm64-profile
        display_flag=--enable-cocoa
    fi
    if [ "$mode" = --cocoa-scanout ]; then
        build_name=build-arm64-scanout
        display_flag=--enable-cocoa
    fi
    if [ "$mode" = --cocoa-activity ]; then
        build_name=build-arm64-activity
        display_flag=--enable-cocoa
    fi
    if [ "$mode" = --cocoa-interaction ]; then
        build_name=build-arm64-interaction
        display_flag=--enable-cocoa
    fi
    set -- "-Dn00_dgles_dir=$dgles_root"
    # The legacy dylibs use basename install names. Only affect this command.
    DYLD_LIBRARY_PATH="$dgles_root/objs-arm64${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
    export DYLD_LIBRARY_PATH
fi
mkdir -p "$source_root/$build_name"
cd "$source_root/$build_name"
if [ ! -f build.ninja ]; then
    ../configure --python="$python_bin" --ninja="$ninja_bin" \
        --target-list=arm-softmmu --enable-tcg --disable-werror \
        --disable-docs --enable-tools --disable-guest-agent \
        --enable-slirp "$display_flag" --disable-sdl --disable-gtk \
        --disable-vnc "$@"
else
    # Reconfigure old builds too: SLIRP must be enabled, and Cocoa must retain
    # the selected DGLES path rather than silently using a previous library.
    ./pyvenv/bin/meson configure -Dslirp=enabled "$@" .
fi
"$ninja_bin" -j "$jobs" qemu-system-arm qemu-img
if [ "$mode" = --cocoa-interaction ]; then
    # Give the native runtime a stable macOS application identity. The normal
    # run script supplies the guest/snapshot arguments, as for the plain binary.
    bundle="$PWD/Harmattan N9.app/Contents"
    mkdir -p "$bundle/MacOS" "$bundle/Resources"
    # Replace the executable atomically; do not overwrite a running preview's
    # vnode or copy the command-line binary's Finder resource fork.
    cp -X qemu-system-arm "$bundle/MacOS/qemu-system-arm.new"
    # LaunchServices does not inherit the run script's DYLD_LIBRARY_PATH.
    # Resolve the legacy basename install name to this build's exact library,
    # also used by its dynamically loaded GLES backends (one EGL instance).
    install_name_tool -change libEGL.1.dylib "$dgles_root/objs-arm64/libEGL.1.dylib" \
        "$bundle/MacOS/qemu-system-arm.new"
    mv -f "$bundle/MacOS/qemu-system-arm.new" "$bundle/MacOS/qemu-system-arm"
    # Optional, separately licensed user-supplied artwork. No image is shipped.
    if [ -f "$port_root/skins/n9-black-livven.png" ]; then
        cp "$port_root/skins/n9-black-livven.png" "$bundle/Resources/"
        cp "$port_root/skins/README.md" "$bundle/Resources/N9-artwork-source.md"
    fi
    cat > "$bundle/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>qemu-system-arm</string>
<key>CFBundleIdentifier</key><string>org.harmattan.qemu.n9</string>
<key>CFBundleName</key><string>Harmattan N9</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>9.1.3</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
    codesign --force --sign - "$PWD/Harmattan N9.app"
    codesign --verify --strict "$PWD/Harmattan N9.app"
    env -u DYLD_LIBRARY_PATH -u DYLD_FALLBACK_LIBRARY_PATH \
        "$bundle/MacOS/qemu-system-arm" --version
fi
file qemu-system-arm qemu-img
./qemu-system-arm --version
echo "Native experimental binaries: $PWD"
