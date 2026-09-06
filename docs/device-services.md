# Original device services: experimental hardware prerequisites

[简体中文](device-services.zh-CN.md) · [Status](status.md) · [Build](building.md)

The complete cellular and power service graph is **not running yet**. The default launcher still uses the minimal rescue startup. `HARMATTAN_N00_SDK_POWER=on` explicitly enables recovered SDK power hardware in a new `--cocoa-interaction` build; the default is `off`. Existing prebuilt applications do not contain this change.

## Implemented scope

- Nokia's BQ24153/BQ24156 charger models at I²C2 addresses `0x6b`/`0x6a`, BQ27521 gauge at `0x55`, and the original TWL GP ADC channels for battery voltage, size and temperature.
- Original N00 OneNAND identity and GPMC CS0/GPIO65 connection, using QEMU's erased, volatile backing when no flash drive is supplied. No CAL contents, certificates or device identity records are synthesized.
- DMA address validation recognizes the actual mapped OneNAND region, including its data buffers after the kernel relocates GPMC CS0. DMA error messages go to stderr, preserving the QMP protocol and error reporting.
- Portable tests cover chip identity, register masks, repeated starts, byte order, reset, unsupported gauge accesses and ADC packing.

These are the historical SDK register models. They contain fixed virtual electrical values and do not model battery discharge over time, a host Mac's battery, a SIM, or a cellular network. Original BME computes the exported battery statistics; there is no replacement statusbar/context provider.

The new flash exists only while QEMU is running, even with a persistent SD user profile. Do not treat it as persistent CAL storage or enable full services on a profile. The standard launcher does not automatically add flash partitions or start BME.

## Bounded BME diagnostic

Follow the build guide and keep the selected DGLES workspace. Use a **quiescent prepared raw disk**, never a live profile or physical device. This command enables the experiment for its own QEMU process, uses `-snapshot`, disables networking, and creates a new output directory:

```sh
export HARMATTAN_DGLES_RUNTIME_DIR="$HARMATTAN_DGLES_ROOT/objs-arm64"
python3 -B scripts/harmattan-qemu/diagnose-sdk-power.py \
  --qemu "$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-arm64-interaction/qemu-system-arm" \
  --kernel "$HARMATTAN_KERNEL" \
  --image "$HARMATTAN_GUEST_IMAGE" \
  --output "$HARMATTAN_PORT_WORKSPACE/sdk-power-diagnostic"
```

Set `HARMATTAN_KERNEL` and `HARMATTAN_GUEST_IMAGE` to the prepared inputs described in [guest inputs](guest-inputs.md). The diagnostic checks the original BME and RX-71 hardware configuration hashes, the SDK `config` partition, BME process/socket liveness, valid `bmestat` levels, QEMU exit and clean host diagnostics. It retains logs and `result.json` locally, including failures. It does not start a desktop.

The guest deliberately runs BME with `-n` to isolate hardware/IPC from DSME. A `PASS` has `full_services: false`; it is not acceptance of full power management, MCE permissions or cellular service.

The pinned original `bmestat` (MD5 `4a509f812807fec894c94e4793f62374`) returns its successful IPC read length, 128, rather than zero. ARM `main` saves the result at `0x9024` and returns it at `0x91bc`; the request at `0xa60c` specifies `0x80` bytes. The diagnostic pins this binary, requires exactly 128 on success, and first requires ENOENT (2) with no BME socket. Other exits are not accepted.

The partition argument comes from the original DFL61 SDK Nolo startup, not the retail N9 layout:

```text
mtdparts=omap2-onenand:128k(bootloader),384k@128k(config),3072k@512k(kernel),1024k@3584k(log),519680k@4608k(swap)
```

## Remaining service dependencies

| Layer | Observed failure / boundary |
| --- | --- |
| BME | I²C detection and CAL-backed startup work. Empty-flash initialization and PMM-table warnings remain; long-session charging/thermal behavior and persistent CAL are unverified. |
| Aegis | On a disk newly prepared from original media, `validator-init` exits 1 with `BB5 open failed -1`; `/dev/omap_sec` is absent. Mounting securityfs exposes credential interfaces but does not initialize the hardware trust chain. |
| DSME | Complete `libstartup.so` startup fails binding the validator notification socket and enters security MALF. The minimal clock heartbeat is not this complete startup. |
| MCE / CSD | Original D-Bus ownership requires `mce::mce` / `csd-base::csd-base` credentials; failed security initialization prevents normal ownership. |
| Cellular transport | The SDK kernel's `omap_ssi` probe reports `SSI HW reset failed`; modem transport, ISI resources, SIM and registration still need implementation and validation. |

Do not remove validator modules, relax the D-Bus policies, replace credential checks, or publish fabricated signal/battery values to make the service graph appear ready. A process existing is insufficient: verify its original identity, bus ownership, transport and consumer state.

## Current validation

The [2026-09-07 validation record](device-services-validation.json) separates 316 passing host tests, fresh DGLES/QEMU source builds, default headless Home startup and the standalone BME diagnostic; all passed.

The early-BME experiment failed compositor readiness and remains FAIL. A separate snapshot first verified Home READY, then started original BME and restarted original sysuid: the statusbar changed from the original very-low icon to the eight-bar icon, with an exact 31-by-20-pixel match to the original asset composited on black. This is a bounded experiment, not default launcher integration. Complete DSME/MCE/CSD checks remain FAIL; Cocoa windows, physical input and long sessions were not tested.

## Source provenance

The register code is recovered from [Nokia revision 32530f6a](https://archive.softwareheritage.org/swh:1:rev:32530f6ab08f80a53bf56843ab793eefde75a67f/), preserving its GPL version 2-or-3 notices. See [sources](sources.md) for the source/binary correspondence boundary.

| Original file | Git/SWH blob | Plain-file SHA-256 |
| --- | --- | --- |
| `hw/n00.c` | `bd7cee59df517c424da543a5a2975532c331fa62` | `95b35044e44e5b1c9a43f9f4da941a79b59e0d4e6a51161e97bd04560f9427de` |
| `hw/nseries.c` | `429bfda407fdc2c8aa0562a1cbc3ddb8a2a99e13` | `6518f2ca11fc88a9f9d1964e03656f427afc70d0d72dc4054aa3bdc4aca33130` |
| `hw/twl4030.c` | `a86855e3463dc64a86547102675e143391c696dc` | `7a8453bd0bca904891137386f184535ca6a37f0acc02e0a0146d990fb5f693bf` |

PR1.3 service contracts were checked against the DVD packages `contextkit-maemo_0.7.30+0m7`, `dsme_0.63.0+0m8`, and `aegis-enabler_0.0.32+0m8`, alongside the original guest binaries. Firmware, CAL data and runtime screenshots are not added to the public source tree.
