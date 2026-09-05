# Build and run

[简体中文](building.zh-CN.md) · [Input provenance](sources.md) · [Status](status.md)

## Supported starting point

The complete build/run path currently targets native **Apple Silicon macOS on APFS**. Linux can run portable host tests; Linux guest execution is an open porting task. QEMU 9.1.3 is pinned because its OMAP foundations match this port, not because it is the newest QEMU release.

There are two independent entry points:

1. **Source work:** host tests and building QEMU/DGLES from public source inputs.
2. **System execution:** additionally supply the historical kernel, adapted PR1.3 guest disk, and read-only guest filesystem used for linking helpers.

The first release does not automate reconstruction of the complete guest disk from a retail firmware container. Do not mistake the source DVD for a bootable image. If you do not already have prepared guest inputs, start with host tests or source builds and see the [guest-preparation roadmap](roadmap.md).

## 1. Host tools

Install Xcode Command Line Tools and provide Python 3.12, Ninja, pkg-config, GLib, Pixman, and a native C compiler. Homebrew users can install missing tools with:

```sh
brew install python@3.12 ninja pkgconf glib pixman
export PATH="$(brew --prefix python@3.12)/libexec/bin:$PATH"
```

Guest helper builds additionally need an LLVM Clang with the ARM backend and `ld.lld`, plus `debugfs` from e2fsprogs. Apple's system linker alone is insufficient. One installation option is:

```sh
brew install llvm lld e2fsprogs
export HARMATTAN_ARMEL_CLANG="$(brew --prefix llvm)/bin/clang"
export HARMATTAN_DEBUGFS="$(brew --prefix e2fsprogs)/sbin/debugfs"
export PATH="$(brew --prefix lld)/bin:$PATH"
```

These commands describe a portable tool selection; the original research used an LLVM toolchain bundled with DevEco Studio. `HARMATTAN_ARMEL_CLANG` accepts that compiler too. A different compiler must pass the guest helper and runtime checks before its output is considered validated. Use `HARMATTAN_PYTHON`, `HARMATTAN_NINJA`, and `HARMATTAN_BUILD_JOBS` to select Python, Ninja, and parallelism.

```sh
python3 scripts/check-environment.py
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py'
```

## 2. Public source inputs

Place these files under the ignored `downloads/tools/` directory, or use the named environment variables:

| Input | Location | Override |
| --- | --- | --- |
| QEMU 9.1.3 release archive | `downloads/tools/qemu-9.1.3.tar.xz` | `HARMATTAN_QEMU_TARBALL` |
| PR1.3 DGLES source package | `downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz` | `HARMATTAN_GLES_TARBALL` |

Obtain QEMU from its [official release archive](https://download.qemu.org/qemu-9.1.3.tar.xz). The DGLES package is in the Harmattan PR1.3 source DVD's `sources/` directory. [sources.md](sources.md) and [inputs.json](inputs.json) provide the exact checksums. Both build scripts reject mismatched archives before extraction.

## 3. Native build

```sh
# Optional: board/display build without the host GLES bridge.
sh scripts/harmattan-qemu/build-arm64-port.sh --headless

# Normal interactive path: build the host library, then QEMU.
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
```

DGLES execution needs a macOS graphics session. Build-only success does not validate rendering. Output lives under ignored `extracted/qemu-arm64-port/`; `HARMATTAN_PORT_WORKSPACE` changes the QEMU workspace and `HARMATTAN_DGLES_WORKSPACE` changes the DGLES workspace. With a custom DGLES location, set `HARMATTAN_DGLES_ROOT` to its built `gles-libs-1.4.2/dgles2` directory when building QEMU.

The maintained patch order is in [architecture.md](architecture.md). The build script applies it. Use a fresh workspace after changing patches; do not replace its pinned archive with another QEMU version.

The first QEMU configure may fetch pinned subprojects from the upstream locations declared in the release's Meson wrap files. Network access is needed when those dependencies are absent. If a fetch is interrupted and leaves a partial subproject, retry in a fresh workspace; archive hash verification does not validate an incomplete dependency checkout.

The local `.app` still references the selected DGLES and Homebrew libraries. Moving those dependencies requires rebuilding. Use the separate [release packager and prebuilt guide](releases.md) for a relocatable application with bundled dependencies.

## 4. User-supplied guest inputs

The normal launcher expects this layout:

```text
extracted/
  pr1.0-qemu-adaptation/
    zImage-2.6.32.26-qemu
    qemu-adaptation.tar.gz
    usr/lib/libEGL.so.1.3.0
    usr/lib/libGLES_CM.so.1.4.5
    usr/lib/libGLESv2.so.1.4.9
    usr/lib/xorg/modules/drivers/omapfb_drv.so
  hybrid-pr1.3-qemu/
    arm-qemu-rm680-image-pr1.3-ui.raw
    pr1.3-rootfs-qemu-rescue.ext4
```

`inputs.json` describes required and optional files. If you have an existing research workspace with this layout, import an explicit allowlist into the new checkout:

```sh
python3 scripts/import-local-inputs.py /path/to/your/research-workspace
python3 scripts/import-local-inputs.py /path/to/your/research-workspace --apply
python3 scripts/check-environment.py --guest
```

The first command is a dry run. The second refuses existing destination files, validates pinned inputs, and APFS-clones large disk files. It never imports logs, accounts, arbitrary folders, or firmware into Git. The main guest disk is prepared local state and has no universal release checksum; the importer records its size and does not claim to validate its contents. Use a trusted, quiescent source copy without personal data.

For manual placement, `HARMATTAN_KERNEL`, `HARMATTAN_GUEST_IMAGE`, and `HARMATTAN_PUBLIC_ROOTFS` can override the kernel, main disk, and helper-linking filesystem. Adaptation libraries retain the documented relative location.

### What a prepared disk contains

The research layout uses an MBR disk with the PR1.3 ext4 root on partition 2 and home data on partition 3, booted with `root=0xB302`. The disk must contain the QEMU rescue `preinit` and the applied PR1.0 adaptation plus UI startup scripts. Raw capacity must be nonzero and at most 32 GiB; the recorded baseline is a sparse 30 GiB disk.

The source helpers for this stage are `preinit-rescue.sh`, `scripts/build-pr13-qemu-ui-overlay.sh`, and `apply-pr13-ui-overlay.sh`. The overlay builder requires the extracted historical adaptation files above. The apply script runs **inside a derived Harmattan guest only**: it writes guest `/usr`, `/lib`, and service permissions. Do not execute it against the host or a physical phone. It does not extract retail firmware or assemble the disk's partitions for you.

## 5. Run and diagnose

```sh
# Wait for READY before interacting. Default: portrait, no artwork.
sh scripts/harmattan-qemu/run-arm64-ui.sh

# Bounded combined regression; starts its own guest and exits.
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-diagnostic
```

The launcher builds helper binaries as needed, creates a private APFS clone plus a qcow2 layer, and uses `-snapshot`. Guest writes are discarded at exit. Each run's files remain in a uniquely named ignored directory for inspection; they are not evidence of persistent Notes storage across launches. Close the source disk's writer before cloning it.

Normal interaction enables WFI, input-driven activity, the original keyboard and animations, and display handoff. Splash stays disabled. Useful overrides:

| Variable | Values / use |
| --- | --- |
| `HARMATTAN_UI_INPUT_ACTIVITY` | `on` / `off`; activity releases after 8 seconds without input |
| `HARMATTAN_UI_SKIN` | `off` (source default) / `frame` (code-drawn, release default) / `black` (requires separately obtained artwork and rebuild) |
| `HARMATTAN_UI_KEYBOARD` | `on` / `off` |
| `HARMATTAN_UI_HANDOFF` | `on` / `off` |
| `HARMATTAN_UI_RUNTIME` | `responsive` (default) / `legacy` (diagnostic comparison) |

Some historical diagnostic modes intentionally use older defaults. A passing combined usability run does not imply every legacy mode passes. `run-pr13-ui.sh` is the historical x86/Rosetta route and writes a persistent derived disk; it is not the recommended native snapshot launcher.

## Troubleshooting

- **Missing archive:** use the exact source package and verify its hash; do not substitute a nearby version.
- **Missing guest input:** consult the manifest. Building QEMU does not create the guest disk.
- **APFS clone failure:** keep the source and runtime workspace on a compatible APFS volume.
- **Guest linker failure:** select LLVM with ARM support and lld; verify `debugfs` and pinned libraries.
- **No graphics session:** run the native graphics test in a logged-in macOS desktop session.
- **Artifact moved:** rebuild the `.app` with the desired library locations.
- **Blank startup:** wait for `READY`, inspect the new run directory, and report the exact command plus a short sanitized failure excerpt.
