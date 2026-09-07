# Experimental PR1.3 kernel

[简体中文](kernel.zh-CN.md) · [Device services](device-services.md) · [Build guide](building.md)

The optional `2.6.32.54-n00-pr13` build brings the original PR1.3 Aegis implementation into the emulator. It is a separate probe kernel, not a replacement for the default SDK kernel or a complete secure-boot implementation. The service prerequisite probe has reached userspace and bound DSME's original netlink protocol 25/group 1. BB5/OMAP security initialization and complete cellular/power services remain incomplete.

## Build on Linux

Use a case-sensitive Linux filesystem, GNU make, patch, tar, Perl, lzop, kmod/depmod, a host C compiler, and an ARM32 GCC 4.x/binutils toolchain. The verified toolchain is GCC 4.9.4 with binutils 2.40; GCC 4.9.4 was built from the [GNU release](https://ftp.gnu.org/gnu/gcc/gcc-4.9.4/) after signature verification. A compiler-only cross build must also locate the ARM assembler and linker; using the build host's assembler is incorrect. macOS can run an isolated Linux build VM, but sources must be unpacked inside its Linux filesystem.

Supply these original source DVD archives. The builder verifies their exact SHA-256 before extraction:

| Archive | SHA-256 |
| --- | --- |
| `kernel_2.6.32-20121301+0m8.tar.gz` | `2ceddaf3a460c21e8ab779393de9096058bf99623e620e42c98bcaf6a65b2cd8` |
| `kernel-qemu_2.6.32.20112701+0m6.tar.gz` | `1599efe16deaaee36bdcea7fa3f95dc6ca80b324c1350d1516695f4708eb7331` |
| `gles-libs_1.4.2-3+0m6.tar.gz` | `2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711` |

Place them in `downloads/tools/`, or set `HARMATTAN_KERNEL_SOURCE`, `HARMATTAN_KERNEL_QEMU_SOURCE` and `HARMATTAN_GLES_TARBALL` to their paths. From a checkout on Linux:

```sh
export HARMATTAN_KERNEL_CROSS_COMPILE=arm-linux-gnueabi-
export HARMATTAN_KERNEL_WORKSPACE="$PWD/extracted/pr13-kernel"
sh scripts/harmattan-qemu/build-pr13-kernel.sh
```

The workspace must not exist. Failed builds are retained. The builder applies the four original `kernel-qemu` patches in Nokia's order, then the maintained Perl/assembler compatibility patch. It preserves `security/aegis` source bytes and required security configuration, keeps original SMC instructions, checks the kernel entry address and validator initializer, and builds matching modules including `kfgles2`. It does not install into a guest or the host.

Modern build compatibility requires `-fcommon` for host helpers, explicit TrustZone assembler support, disabling the misplaced build-id note, and ARM flags `-mno-unaligned-access -fno-builtin`. The latter preserves the old ARM `memset` macro contract; allowing standard-library return-value assumptions corrupted console font allocations. SLUB debug repair is not a fix or an accepted startup path. Diagnostics reject kernel faults and allocator corruption even if a shell eventually appears.

Module packaging converts dependency entries to the absolute paths consumed by Harmattan's original module-init-tools and removes modern binary indexes. Both case-distinct netfilter modules are retained. Legacy depmod warnings about absent `modules.order` and built-in metadata remain in the build log.

## Prepare a private probe on macOS

Transfer `kernel-bundle.tar.gz` intact. Do not unpack its modules onto a case-insensitive filesystem: `xt_RATEEST.ko` and `xt_rateest.ko` are different modules. The following helper validates every output hash, stages modules under numeric host filenames, APFS-clones a quiescent prepared disk, and installs only the matching module directory into its ext4 root:

```sh
python3 -B scripts/harmattan-qemu/prepare-pr13-kernel-probe.py \
  --bundle "$HARMATTAN_KERNEL_BUNDLE" \
  --image "$HARMATTAN_GUEST_IMAGE" \
  --debugfs "$HARMATTAN_DEBUGFS" \
  --output "$PWD/extracted/pr13-kernel-probe"
```

Use a fresh output directory. It contains `disk.raw`, `zImage-2.6.32.54-n00-pr13`, a working root slice and local provenance. It preserves the original disk and its `/lib/modules/current` symlink; this is a scoped prerequisite probe, not a general UI migration. Run the [service prerequisite diagnostic](device-services.md#hardware-and-security-prerequisites) with those new disk/kernel paths and `HARMATTAN_N00_SSI=on`; it uses `-snapshot` and no network. Do not apply this to a live profile or phone.

The bundle and derived disk are private build artifacts. No firmware, certificates or device identity are generated or published. A compiled Aegis implementation and a successful netlink bind do not supply a secure monitor, verified KCI handoff, PA signatures, BB5 credentials, a modem or SIM.

## Verification and remaining blockers

The [2026-09-07 validation record](kernel-validation.json) covers a clean Linux source build, 101 matching modules, unchanged original Aegis source files, 338 host tests, a headless prerequisite probe, and the original SDK/BME regression. The new kernel binds validator netlink and the original SSI driver; all six selected SSI/CMT/Phonet/GLES modules load. Loading `kfgles2` is not graphics acceptance.

A separate bounded snapshot attempted the full original service configurations. DSME loaded `libstartup.so`, entered USER state, received validator notifications, and owned `com.nokia.dsme` plus its disk monitor, power-on timer and thermal-manager names. It used the existing `no-ext-wd,no-omap-wd` diagnostic flags; watchdog behavior was not tested. BME ran without `-n`, but DSME rejected its IPC connection for missing `dsme::DeviceStateControl`, so BME exited and `bmestat` returned 2. MCE and CSD also failed required bus ownership; a surviving CSD process is not readiness.

`validator-init` still exits 1, `/dev/omap_sec` is absent and KCI remains zero. The snapshot reports original validator `enabled=1, enforce=0`; no enforcement setting was changed, and this is not signature/credential acceptance. The next required security work is a compatible secure backend and verified boot handoff followed by original BB5/Aegis credential initialization. The modem/ISI peer is also missing. Default-launcher integration, new-kernel UI/Cocoa behavior, physical input and long sessions remain untested; complete services remain BLOCKED.
