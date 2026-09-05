# Prebuilt macOS preview

[简体中文](releases.zh-CN.md)

Download application and corresponding source assets from [GitHub Releases](https://github.com/YZune/harmattan-qemu/releases). This experimental ARM64 macOS preview bundles QEMU, DGLES, their non-system dynamic dependencies, a private Python 3.12.14 controller runtime and precompiled guest helpers. No Homebrew, Python installation, LLVM or debugfs is needed to use the app.

## What you still need

- Apple Silicon macOS meeting the release's `minimum_macos` value, and an APFS volume for the imported disk and temporary clones. Read the individual release's tested host; a successful test on one Mac does not prove all supported OS versions.
- A **prepared PR1.3 raw disk**, with the Linux/ext root filesystem on partition 2, at most 32 GiB. This is the disk used by the existing native launcher.
- `zImage-2.6.32.26-qemu`, SHA-256 `4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e`.

The app does **not** convert retail firmware, a source DVD, a rootfs-only file or QCOW2 into that prepared disk. It does not include firmware, guest kernels, fonts, guest linking libraries, SDK installers or Livven artwork. The remaining original-media preparation gap is a priority for contributors. See the [input inventory](https://github.com/YZune/harmattan-qemu/blob/main/docs/inputs.json).

## Use the application

1. Verify the release's `SHA256SUMS`, unzip the application and move it to a writable local folder such as Applications.
2. Open **Harmattan QEMU.app**. On first launch, choose the prepared `.raw` disk, then the matching kernel. Stop writers to the source disk before importing. Import creates private APFS copies and records a disk checksum; it does not edit the originals.
3. Wait for the original Home screen. The default device frame is drawn by project code and contains no external artwork or logo. The existing source build can still use separately supplied artwork.
4. Drag to scroll, use the on-screen keyboard, and close QEMU to end the session. Guest changes, including Notes, are discarded when the snapshot ends.

This initial package is **ad-hoc signed, not Developer ID signed or notarized**. A downloaded app may need approval through macOS Privacy & Security after an attempted launch. Verify its origin and checksum first; do not disable Gatekeeper globally. Managed Macs may require their administrator's distribution policy.

Inputs and configuration live in `~/Library/Application Support/Harmattan QEMU/`. `launcher.log` records the latest GUI launch; `last-run.txt` points to its retained temporary diagnostic workspace. Old imported profiles remain under `inputs/` when replaced. Remove only identified, inactive profiles/runs you no longer need. Preserve source inputs separately: GitHub is not their backup.

## Command-line entry

Run from the folder containing the app:

```sh
APP='./Harmattan QEMU.app/Contents/MacOS/harmattan'
"$APP" import --disk /path/to/prepared.raw --kernel /path/to/zImage-2.6.32.26-qemu
"$APP" check
"$APP" run
"$APP" run --diagnostic
```

`import --replace` creates a new profile while retaining the previous one. `--configure` opens the file selection UI again. `run --no-frame` uses the plain framebuffer window. `HARMATTAN_DATA_HOME` selects a separate state directory for testing. The combined `run --diagnostic` is a bounded headless guest regression, not a mouse or visible-window test. Errors in helper hashes, kernel identity or guest component validators stop the run; there is no compile fallback.

## Preserved sources and rebuilding

Each binary release must be accompanied by its corresponding source kit and license notices, not just a link to an upstream download. The kit contains this project's source/patches/scripts, pinned upstream QEMU and DGLES archives, the previously network-fetched DTC source, Python source, bundled library sources, installed Homebrew recipes and their GLib patch, and the patched QEMU/DGLES source trees. Source checksums are recorded in `docs/inputs.json` and `docs/release-sources.json`.

The source kit keeps the repository under `project/`, with `prepared-source/`, `build-recipes/` and `third-party-licenses/` alongside it. Run repository commands from `project/`. Keep an independent copy of release assets. Offline source verification is available with:

```sh
python3 scripts/release/fetch-sources.py --offline
```

This verifies preserved release inputs; it does not install host build tools. Full builds still require the native toolchain from [the build guide](https://github.com/YZune/harmattan-qemu/blob/main/docs/building.md). QEMU's Python build environment also requires Meson 1.2.3 or a supported installed version. Source-kit `build-recipes/` records actual configure choices and the modifications to Homebrew libraries. Inherited license terms remain in force; this project does not relicense third-party code.

For maintainers, create fresh native QEMU/DGLES workspaces with `build-dgles2-host.sh` and `build-arm64-port.sh --cocoa-interaction`. Use a neutral build path to keep personal paths out of binaries. The builder automatically consumes `downloads/tools/qemu-dtc-b6910bec.tar` when present; `HARMATTAN_DTC_TARBALL` can select it explicitly. Export that archive with `git archive --format=tar --prefix=dtc/ b6910bec11614980a21e46fbccc35934b671bd81` from the exact upstream DTC commit if restoring a missing cache.

```sh
python3 scripts/release/fetch-sources.py
sh scripts/release/build-python.sh downloads/tools/Python-3.12.14.tar.xz /tmp/new-python-work
# Select HARMATTAN_ARMEL_CLANG and HARMATTAN_DEBUGFS for the build machine.
# Guest link inputs must be available when compiling helpers; they are not packaged.
python3 scripts/release/package-macos.py \
  --qemu-source /tmp/native-work/qemu-9.1.3-interaction \
  --dgles-source /tmp/native-work/dgles2-host/gles-libs-1.4.2 \
  --python-work /tmp/new-python-work \
  --helper-work /tmp/new-helper-work \
  --output artifacts/new-release
```

Packaging verifies library dependency closure, source hashes, helper ELF/source hashes and signatures. Before publishing, move the app to another directory, use a clean environment with only system utilities, run the guest regression and inspect the native frame. Check the **assembled source kit and binary package** for accidental local inputs as well as running the repository publication check. Attach concise evidence to the release; do not claim a second-machine or notarization check unless performed.

Dynamic LGPL libraries remain separate files in `Contents/Frameworks`; recipients can rebuild/replace them under their licenses and apply a local signature to their modified bundle. The supplied source kit and build/relocation scripts support this. See [third-party notices](https://github.com/YZune/harmattan-qemu/blob/main/docs/THIRD_PARTY_NOTICES.md).

After runtime verification, finalize assets with `python3 scripts/release/verify-release.py artifacts/new-release --archive`. This verifies exact project-source equality, bundle contents, load paths, signatures and pinned archives before creating the application ZIP, source tarball and checksums.

The convenient patched source trees omit upstream symlinks pointing outside those trees; their paths and targets are recorded in `build-recipes/*-external-links.json`. The pinned upstream archives remain unchanged.
