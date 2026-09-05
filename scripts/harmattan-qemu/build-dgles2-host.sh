#!/bin/sh
# Build the isolated, opt-in native macOS backend; never install globally.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_DGLES_WORKSPACE:-"$repo_root/extracted/qemu-arm64-port/dgles2-host"}
archive=${HARMATTAN_GLES_TARBALL:-"$repo_root/downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz"}
patch_file="$repo_root/ports/dgles2/gles-libs-1.4.2-cocoa-fbo.patch"
compiler=${HARMATTAN_CC:-clang}
jobs=${HARMATTAN_BUILD_JOBS:-8}

if [ "$(uname -s):$(uname -m)" != Darwin:arm64 ]; then
    echo 'Use a native arm64 macOS shell, not Rosetta.' >&2
    exit 1
fi
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
    if git apply --reverse --check "$patch_file" >/dev/null 2>&1; then
        echo 'DGLES2 native offscreen patch already applied.'
    elif git apply --check "$patch_file"; then
        git apply "$patch_file"
    else
        echo 'Source differs from patch; retained for inspection. Choose a fresh HARMATTAN_DGLES_WORKSPACE.' >&2
        exit 1
    fi
)

cd "$source_root/dgles2"
build_log=$(mktemp "$work_root/build.XXXXXX")
if [ ! -f config-arm64.mak ]; then
    ./configure --arch=arm64 --disable-osmesa --enable-cocoa --enable-offscreen \
        --disable-x11 --disable-glx --disable-wgl --prefix="$work_root/install"
fi
# Legacy Makefiles do not track all included headers; force these small
# libraries to rebuild rather than accidentally test objects with an old ABI.
if ! make -B -j "$jobs" CC="$compiler" >"$build_log" 2>&1; then
    tail -80 "$build_log" >&2
    echo "Build failed; full log: $build_log" >&2
    exit 1
fi
"$compiler" -arch arm64 -std=c99 -Wall -Wextra -O2 -Iinclude \
    "$repo_root/scripts/harmattan-qemu/smoke-dgles2-host.c" \
    -Lobjs-arm64 -lEGL -lGLESv2 -o "$work_root/smoke-dgles2-host"
"$compiler" -arch arm64 -std=c99 -Wall -Wextra -O2 -DDGLES_TEST_ES1 -Iinclude \
    "$repo_root/scripts/harmattan-qemu/smoke-dgles2-host.c" \
    -Lobjs-arm64 -lEGL -lGLES_CM -o "$work_root/smoke-dgles1-host"
file objs-arm64/libEGL.1.4.2.dylib objs-arm64/libGLESv2.2.0.0.dylib \
    objs-arm64/libGLES_CM.1.4.1.dylib "$work_root/smoke-dgles2-host" "$work_root/smoke-dgles1-host"
echo "Build log (including legacy OpenGL deprecation warnings): $build_log"
echo 'Built only; graphics execution requires access to the macOS graphics session.'
echo "Test: python3 -B $repo_root/scripts/harmattan-qemu/smoke-dgles-host.py --workspace $work_root"
