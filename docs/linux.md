# Experimental Linux offscreen runtime

[简体中文](linux.zh-CN.md) · [Build guide](building.md) · [Native window](linux-native.md) · [Validation record](linux-validation.json)

This is the bounded Linux host path for [issue #3](https://github.com/YZune/harmattan-qemu/issues/3): x86_64 Linux, ARM32 TCG, DGLES with Mesa OSMesa software rendering, and QMP input/framebuffer capture. It produces real guest pixels without a host GPU, X11, Wayland or a desktop session. The opt-in [Godot native window](linux-native.md) adds scoped desktop input over this offscreen backend; an installer, touch hardware and full device services remain separate work. The Apple Silicon Cocoa path keeps its existing defaults.

## Design

- The existing QEMU 9.1.3 patch stack supplies the N00 board and guest graphics protocol. The explicit Linux build selects ELF libraries and OSMesa; it does not build Cocoa.
- DGLES uses the pinned original ABI headers and the OSMesa backend. Surface bounds, ownership, resize, flush and unbind checks protect the callback pixel target. GLES1 and GLES2 share the same lifecycle rules.
- QEMU stops graphics workers during normal VM cleanup, before Mesa's process-exit handlers. An idempotent exit fallback remains. Deferring the only cleanup to `atexit()` caused a reproducible `glFinish` crash after Mesa teardown.
- Preparation uses GNU `cp --reflink=auto --sparse=always` and stages beside the output on Linux. Every UI run uses a new qcow2 overlay plus `-snapshot`; the prepared raw image remains the read-only backing file. Keep the base image quiescent.
- The bounded launcher uses QMP on stdio and private mode-0600 serial FIFOs. Networking is disabled and no control listener is opened. Original guest identity, ABI hashes, readiness, pixels, faults and worker-join gates remain active.

## 1. Host dependencies

The recorded host was Debian 13.6 x86_64, Python 3.12.14, GCC 14.2, Clang/LLD 19.1.7, Ninja 1.12.1 and Mesa 25.0.7. Other distributions/tool versions require their own validation. Python must be 3.12 or newer. On a Debian 13 development host, the corresponding packages are:

```sh
sudo apt install build-essential git curl xz-utils file perl ninja-build pkg-config \
  python3 python3-venv python3-distlib python3-pil meson \
  libglib2.0-dev libpixman-1-dev libslirp-dev libfdt-dev libosmesa6-dev \
  clang-19 lld-19 e2fsprogs 7zip liblzo2-2
export HARMATTAN_ARMEL_CLANG=clang-19
export HARMATTAN_DEBUGFS=/usr/sbin/debugfs
```

Pillow must be importable by the Python used for the launcher. It only exports diagnostic PPM captures as lossless PNGs and verifies the decoded RGB bytes. Compiler/linker and shared-library search paths may instead point at a private dependency installation. The recorded run used private official Debian packages; it did not replace system libraries.

## 2. Obtain the pinned public sources

Run from the repository root. The source kit supplies DGLES sources, not a guest disk.

```sh
mkdir -p downloads/tools
curl --fail --location -o downloads/tools/qemu-9.1.3.tar.xz \
  https://download.qemu.org/qemu-9.1.3.tar.xz
curl --fail --location \
  -o downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz \
  https://github.com/YZune/harmattan-qemu/releases/download/v0.1.0-preview.1/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz
sha256sum --check <<'EOF'
480a77a0ed13a9b39415f639aa020b4eb0d7cc5a52569510dfd830b3af1bac89  downloads/tools/qemu-9.1.3.tar.xz
c9e3eb01f9b828169d00570dfb17b24d5375cce6bee739874149dce19ed4edcc  downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz
EOF
tar -xOf downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz \
  harmattan-qemu-sources/project/downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz \
  > downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz
sha256sum --check <<'EOF'
2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711  downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz
EOF
```

Stop on a checksum failure. The build scripts independently verify both pinned input archives. The source-kit member and its complete checksum were verified locally on 2026-10-08. See [source attribution](sources.md) and [NOTICE](../NOTICE); components retain their own licenses.

## 3. Build and check without firmware

Use a fresh workspace after patch changes. Keep these exports for every subsequent command; separate shells do not inherit a previous tool invocation's exports.

```sh
export HARMATTAN_PORT_WORKSPACE="$PWD/extracted/qemu-linux-port"
export HARMATTAN_DGLES_WORKSPACE="$HARMATTAN_PORT_WORKSPACE/dgles2-host"
export HARMATTAN_DGLES_ROOT="$HARMATTAN_DGLES_WORKSPACE/gles-libs-1.4.2/dgles2"
export HARMATTAN_BUILD_JOBS=4
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py \
  --workspace "$HARMATTAN_DGLES_WORKSPACE"
sh scripts/harmattan-qemu/build-arm64-port.sh --linux-interaction
HARMATTAN_LINUX_BUILD="$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-linux-interaction"
python3 -B scripts/harmattan-qemu/smoke-qemu-linux-cleanup.py \
  --qemu "$HARMATTAN_LINUX_BUILD/qemu-system-arm" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --output extracted/linux-cleanup-check
```

The cleanup probe requires glibc and a fresh output directory. Its tiny synthetic ARM fixture checks prelaunch/running/paused worker teardown before libc process-exit handlers; it does not boot an operating system or create a Mesa rendering context. The DGLES smoke separately checks real Mesa contexts, pixels and teardown.

QEMU's first configure may fetch its pinned Meson subprojects. A complete build requires the ordinary compiler/development dependencies above. The binaries stay in the selected build tree; this is not a relocatable release package.

Keep the exact renderer printed by the successful DGLES smoke test. The historical result was `llvmpipe (LLVM 19.1.7, 256 bits)`. The guest validator requires an explicit exact match, not any renderer that happens to contain `Mesa`.

## 4. Prepare the historical guest locally

Follow [Get guest inputs](guest-inputs.md) for the exact two media downloads and hashes. The Windows installer is only unpacked as an archive. Neither it nor any extracted host installer is executed. No guest material is included in Git.

Reserve at least 30 GiB free for downloads, intermediate files and sparse outputs. The raw disk has 32 GiB logical capacity; never copy it with a tool that expands its holes. Linux stages on the destination filesystem, so a small `/tmp` is not used for large images. Select a new output directory:

```sh
HARMATTAN_LINUX_BUILD="$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-linux-interaction"
export LD_LIBRARY_PATH="$HARMATTAN_DGLES_ROOT/objs-x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python3 -B scripts/prepare-guest.py \
  --sdk-exe downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  --firmware downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  --output extracted/guest-from-original-media-linux \
  --sevenzip "$(command -v 7zz)" --debugfs "$HARMATTAN_DEBUGFS" \
  --lzo-library /usr/lib/x86_64-linux-gnu/liblzo2.so.2 \
  --qemu-img "$HARMATTAN_LINUX_BUILD/qemu-img" \
  --qemu-system-arm "$HARMATTAN_LINUX_BUILD/qemu-system-arm"
```

Use your distribution's actual 7-Zip executable (`7z` on some installations). Preparation verifies media and ABI identities, adapts only the new disk inside the offline guest, then requires both the completion marker and clean QEMU exit. Failed preparation retains its stage for diagnosis. Do not run the guest overlay apply script on the host.

## 5. Run the bounded UI diagnostics

Use the exact renderer from step 3. Paths are explicit to avoid silently selecting another historical image. The prepared folder supplies the kernel, raw disk, helper rootfs and original SDK link libraries; no copy into a second legacy layout is needed.

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' --mode startup
```

After startup passes, repeat with `--mode usability --timeout 900` for original Home, Notes/Maliit, Calculator and bounded transition checks. Each invocation creates its own diagnostic directory; `--output` can select a new one. `--prepare-only` builds the pinned ARM guest helpers without starting the UI.

A successful result requires QEMU exit 0, clean graphics lifecycle/worker joins, no unknown faults/rejections, and all selected guest gates. Captures are actual QMP framebuffer output; PNG provenance records verify equality with the authoritative PPM pixels. These are QMP simulated-input tests, not physical touch or display-FPS measurements. Linux permits a bounded 30-poll System UI readiness budget for software-renderer latency; the original default and readiness predicates remain unchanged.

## Evidence and remaining limits

The [validation record](linux-validation.json) separates the 2026-10-08 experiment from integration checks. The experiment reached original Home in 103.314 seconds, passed Notes typing/deletion/symbols/save/reopen and Calculator `2+3=5`, and exited cleanly with all workers joined and zero graphics faults/rejections. Raw disk, kernel and exported rootfs hashes stayed unchanged. Earlier failed readiness/teardown attempts were retained and informed the fixes.

The full host suite failed in that restricted environment because Unix sockets and LeakSanitizer were unavailable; focused tests and actual guest success do not convert that into a suite pass. AppKit tests skipped on Linux. Integration CI and current source-build checks are reported separately. macOS runtime was not rerun for this Linux change.

This offscreen record does not establish full retail startup, cellular/audio/network/browser/camera services, arbitrary application compatibility, persistent profiles or long-session stability. The [native window record](linux-native-validation.json) separately documents scoped desktop interaction and its verification limits.
