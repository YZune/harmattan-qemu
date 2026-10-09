#!/bin/sh
# Build isolated, opt-in host graphics backends; never install globally.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
host=$(uname -s):$(uname -m)
workspace_name=qemu-arm64-port
if [ "$host" = Linux:x86_64 ]; then workspace_name=qemu-linux-port; fi
port_work_root="$repo_root/extracted/$workspace_name"
if [ "$host" = Linux:x86_64 ]; then
    port_work_root=${HARMATTAN_PORT_WORKSPACE:-"$port_work_root"}
fi
work_root=${HARMATTAN_DGLES_WORKSPACE:-"$port_work_root/dgles2-host"}
archive=${HARMATTAN_GLES_TARBALL:-"$repo_root/downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz"}
patch_file="$repo_root/ports/dgles2/gles-libs-1.4.2-cocoa-fbo.patch"
compiler=${HARMATTAN_CC:-clang}
if [ "$host" = Linux:x86_64 ]; then compiler=${HARMATTAN_CC:-cc}; fi
linux_patch="$repo_root/ports/dgles2/gles-libs-1.4.2-linux-osmesa.patch"
jobs=${HARMATTAN_BUILD_JOBS:-8}

case "$host" in
    Darwin:arm64) arch=arm64 ;;
    Linux:x86_64) arch=x86_64 ;;
    *) echo 'Use native arm64 macOS or experimental Linux x86_64.' >&2; exit 1 ;;
esac
if [ ! -f "$archive" ]; then
    echo "Missing PR1.3 source archive: $archive" >&2
    echo 'Set HARMATTAN_GLES_TARBALL to sources/gles-libs_1.4.2-3+0m6.tar.gz on the source DVD.' >&2
    exit 1
fi
actual_sha=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
if [ "$actual_sha" != 2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711 ]; then
    echo 'DGLES2 source archive SHA-256 mismatch; refusing to extract or patch.' >&2
    exit 1
fi
compiler=$(command -v "$compiler")
"$compiler" --version
mkdir -p "$work_root"
work_root=$(CDPATH= cd -- "$work_root" && pwd)
source_root="$work_root/gles-libs-1.4.2"
if [ ! -d "$source_root" ]; then
    tar -xzf "$archive" -C "$work_root"
fi
(
    cd "$source_root"
    export GIT_CEILING_DIRECTORIES="$work_root"
    if [ "$host" = Linux:x86_64 ] && git apply --reverse --check "$linux_patch" >/dev/null 2>&1; then
        git apply --reverse "$linux_patch"
    fi
    if git apply --reverse --check "$patch_file" >/dev/null 2>&1; then
        echo 'DGLES2 native offscreen patch already applied.'
    elif git apply --check "$patch_file"; then
        git apply "$patch_file"
    else
        echo 'Source differs from patch; retained for inspection. Choose a fresh HARMATTAN_DGLES_WORKSPACE.' >&2
        exit 1
    fi
    if [ "$host" = Linux:x86_64 ]; then
        git apply --check "$linux_patch"
        git apply "$linux_patch"
    fi
)

cd "$source_root/dgles2"
build_log=$(mktemp "$work_root/build.XXXXXX")
if [ ! -f "config-$arch.mak" ]; then
    if [ "$host" = Linux:x86_64 ]; then
        ./configure --arch=x86_64 --enable-osmesa --disable-cocoa --enable-offscreen \
            --disable-x11 --disable-glx --disable-wgl --prefix="$work_root/install"
    else
        ./configure --arch=arm64 --disable-osmesa --enable-cocoa --enable-offscreen \
            --disable-x11 --disable-glx --disable-wgl --prefix="$work_root/install"
    fi
fi
# Legacy Makefiles do not track all included headers; force these small
# libraries to rebuild rather than accidentally test objects with an old ABI.
# Use the bundled DGLES/OSMesa ABI headers, not system desktop GL headers.
if [ "$host" = Linux:x86_64 ]; then
    CFLAGS="${CFLAGS:-} -DMESA_EGL_NO_X11_HEADERS"
    export CFLAGS
fi
if ! make -B -j "$jobs" ARCH="$arch" CC="$compiler" >"$build_log" 2>&1; then
    tail -80 "$build_log" >&2
    echo "Build failed; full log: $build_log" >&2
    exit 1
fi
set -- -arch arm64
if [ "$host" = Linux:x86_64 ]; then set -- -D_GNU_SOURCE -pthread -ldl; fi
"$compiler" -std=c99 -Wall -Wextra -O2 -Iinclude \
    "$repo_root/scripts/harmattan-qemu/smoke-dgles2-host.c" \
    -L"objs-$arch" -lEGL -lGLESv2 "$@" -o "$work_root/smoke-dgles2-host"
"$compiler" -std=c99 -Wall -Wextra -O2 -DDGLES_TEST_ES1 -Iinclude \
    "$repo_root/scripts/harmattan-qemu/smoke-dgles2-host.c" \
    -L"objs-$arch" -lEGL -lGLES_CM "$@" -o "$work_root/smoke-dgles1-host"
file "objs-$arch"/libEGL.* "objs-$arch"/libGLESv2.* \
    "objs-$arch"/libGLES_CM.* "$work_root/smoke-dgles2-host" "$work_root/smoke-dgles1-host"
echo "Build log (including legacy OpenGL deprecation warnings): $build_log"
if [ "$host" = Darwin:arm64 ]; then
    echo 'Built only; graphics execution requires access to the macOS graphics session.'
else
    echo 'Built only; Linux execution requires libOSMesa.so.8 and a software Mesa driver.'
fi
echo "Test: python3 -B $repo_root/scripts/harmattan-qemu/smoke-dgles-host.py --workspace $work_root"
