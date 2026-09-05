# Get the kernel and prepare a guest disk

[简体中文](guest-inputs.zh-CN.md) · [Prebuilt application](releases.md) · [Media identities](guest-media.json)

The application needs two files: a prepared PR1.3 `.raw` disk and `zImage-2.6.32.26-qemu`. There is no project-hosted guest image to download. This guide creates those files locally from two precisely identified original archives. Downloading retail firmware alone does not produce an importable disk.

Run the commands from a current checkout. If you do not have one yet:

```sh
git clone https://github.com/YZune/harmattan-qemu.git
cd harmattan-qemu
```

## 1. Download the original media

| Material | Exact file | Size | Purpose |
| --- | --- | ---: | --- |
| [Nokia Qt SDK 1.1.2 archive](https://archive.org/details/nokia-qt-sdk-1.1.2) | [Qt_SDK_Win_offline_v1_1_2_en.exe](https://archive.org/download/nokia-qt-sdk-1.1.2/Qt_SDK_Win_offline_v1_1_2_en.exe) | 1,907,658,896 bytes | PR1.0 emulator kernel, graphics adaptation and original SDK disk layout |
| [Nokia N9 RM696 archive](https://archive.org/details/RM696) | [DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin](https://archive.org/download/RM696/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin) | 1,248,135,798 bytes | PR1.3 global retail root filesystem |

The Windows installer is used as an archive **on macOS**. Do not execute or install it. No Windows, Wine, historical SDK installation or phone is involved. The firmware is not flashed to a device.

Both exact download endpoints returned HTTP 200 with the expected lengths on 2026-09-05. Archive metadata also matched the historical SHA-1 identities; the preparation script verifies the complete files with the SHA-256 values below. Availability can change, so preserve your original downloads and their checksums independently. A mirror is acceptable only when the complete file matches; do not substitute a different region, PR release, SDK version, EMMC image, source ISO or phone/openmode kernel. Archive availability does not grant redistribution rights.

From this repository root, download through the links above into `downloads/guest-media/`, or use:

```sh
mkdir -p downloads/guest-media
curl --fail --location --continue-at - \
  --output downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  https://archive.org/download/nokia-qt-sdk-1.1.2/Qt_SDK_Win_offline_v1_1_2_en.exe
curl --fail --location --continue-at - \
  --output downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  https://archive.org/download/RM696/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin
```

Expected SHA-256 values (also in [guest-media.json](guest-media.json)):

```text
ce16cbd7c99e607f51789d857fe8573852a999053a79af1fa20d645457044e30  Qt_SDK_Win_offline_v1_1_2_en.exe
9614f29594f77f50dbd34d0f921c69a4e3511fc1373dfb7467d1b0e073ea3d51  DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin
```

`shasum -a 256 downloads/guest-media/*` prints local hashes for comparison. The script rejects wrong size/hash before creating its work directory.

## 2. Prepare tools once

This preparation route currently targets Apple Silicon macOS 26.0 or newer (the Preview 1 app's requirement) and the system APFS volume. Reserve at least 30 GiB of free space for original media, intermediate files and the sparse output. The disk's logical capacity is 32 GiB; copying it with a tool that expands sparse holes can require much more space.

Use Python 3.12 or newer, 7-Zip (`7zz`), `debugfs` and liblzo2. Homebrew users can install missing tools:

```sh
brew install python@3.12 sevenzip e2fsprogs lzo
```

The package names and `7zz` executable are documented by Homebrew: [sevenzip](https://formulae.brew.sh/formula/sevenzip), [e2fsprogs](https://formulae.brew.sh/formula/e2fsprogs), [lzo](https://formulae.brew.sh/formula/lzo). These tools are needed to prepare original media; ordinary launches of an already configured prebuilt app do not need them.

Download and unzip the [macOS prebuilt application](https://github.com/YZune/harmattan-qemu/releases/tag/v0.1.0-preview.1). It supplies the matching `qemu-img` and native `qemu-system-arm`. An ordinary upstream QEMU installation lacks this project's machine model. If macOS blocks a downloaded executable, follow the signing information in [releases.md](releases.md).

## 3. Create a new disk

Use the current repository checkout: the original Preview 1 source tarball predates this preparation script. In the example, the app is in `/Applications`; change `HARMATTAN_APP` to its actual location. Keep `--output` on the system APFS volume. The output must not already exist.

```sh
HARMATTAN_APP='/Applications/Harmattan QEMU.app'
"$(brew --prefix python@3.12)/bin/python3.12" -B scripts/prepare-guest.py \
  --sdk-exe downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  --firmware downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  --output extracted/guest-from-original-media \
  --sevenzip "$(brew --prefix sevenzip)/bin/7zz" \
  --debugfs "$(brew --prefix e2fsprogs)/sbin/debugfs" \
  --lzo-library "$(brew --prefix lzo)/lib/liblzo2.dylib" \
  --qemu-img "$HARMATTAN_APP/Contents/MacOS/qemu-img" \
  --qemu-system-arm "$HARMATTAN_APP/Contents/MacOS/qemu-system-arm"
```

The script validates both complete inputs, extracts only the pinned SDK runtime member, verifies the kernel and graphics libraries, restores and verifies the PR1.3 rootfs, and assembles a new sparse disk. It preserves the factory SDK data/home partitions and replaces the root partition with PR1.3. It then boots the new disk headlessly, applies the maintained compatibility overlay inside that guest, syncs and remounts the root read-only before stopping its own QEMU process. No existing research image, host filesystem mount, root privileges or device access is used.

Internal extraction offsets are specific to the hash-checked media, not a generic installer/firmware parser. The intermediate rootfs is independently checked before modification. A successful preparation run does not yet establish UI compatibility: run the next diagnostic.

## 4. Import and verify

Successful output includes:

| File | Use |
| --- | --- |
| `harmattan-pr1.3.raw` | Select this in the app's disk picker |
| `zImage-2.6.32.26-qemu` | Select this in the kernel picker; SHA-256 `4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e` |
| `prepared-inputs.json` | Original-media and derived-output identities |
| `pr1.3-rootfs-qemu-rescue.ext4` | Completed root filesystem for source-build helper linking; not the app's disk input |
| `prepare-serial.log` | In-guest preparation evidence |

Alternatively, import and test from the terminal:

```sh
HARMATTAN_APP='/Applications/Harmattan QEMU.app'
"$HARMATTAN_APP/Contents/MacOS/harmattan" import \
  --disk extracted/guest-from-original-media/harmattan-pr1.3.raw \
  --kernel extracted/guest-from-original-media/zImage-2.6.32.26-qemu
"$HARMATTAN_APP/Contents/MacOS/harmattan" run --diagnostic
"$HARMATTAN_APP/Contents/MacOS/harmattan" run
```

If the app already has a profile, `import --replace` creates another while retaining the old one. Preparation finishes all guest writes before import. The app clones these inputs; normal session writes are discarded on exit.

## Failures and preservation

- **Wrong input:** use the exact filename and compare the full SHA-256. A renamed different file remains incompatible.
- **Preparation failed:** the printed `harmattan-prepare-*` path retains logs and intermediates. No completed output is announced. Correct the cause and retry; an existing completed output is never overwritten.
- **Overlay boot failed:** inspect `prepare-serial.log` and the `*.log`/`*.commands` files. Do not apply guest scripts to the host or a phone.
- **Output rename failed:** keep it on the same system APFS volume as `/private/tmp`; the script refuses a cross-volume copy of large images.
- **Preservation:** keep both original downloads, the repository revision, the prebuilt application's corresponding source kit, and the completed input folder separately. Git ignores these materials. Remove only an identified inactive failed workspace after retaining any useful evidence.

The project distributes the preparation code and media identities. It does not distribute the SDK, firmware, extracted kernel or prepared guest disk. The generated system remains the PR1.3 userspace / PR1.0 emulator-kernel combination with the runtime limitations in [status.md](status.md).

On 2026-09-05 this complete path passed on macOS 26.6.2: original-media extraction, guest adaptation, a read-only filesystem check and the published app's combined headless Home/Notes/keyboard/Calculator/transition diagnostic. All 246 host tests passed. Another Mac, a fresh tool installation and GUI input on this new disk remain unverified. See the [validation record](guest-preparation-validation.json); derived filesystem timestamps are not promised to be bit-identical between runs.
