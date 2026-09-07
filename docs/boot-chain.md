# Boot-chain inputs and GP bootstrap services

[简体中文](boot-chain.zh-CN.md) · [Device services](device-services.md) · [Kernel](kernel.md)

Full secure boot is still **BLOCKED**. This work prepares original boot/modem inputs and restores the missing GP `CONTROL_STATUS` mapping. An opt-in cache-only GP monitor now supports the original loader's first SMC; it does not provide HS/BB5 security services, provision storage or grant credentials.

## Prepare original payloads

Use the exact PR1.3 firmware identified in [guest media](guest-media.json). The command reads the original file, verifies its complete size/SHA-256 before creating output, validates all FIASCO record boundaries and header checksums, and verifies the original media again before writing the completion manifest:

```sh
python3 -B scripts/harmattan-qemu/prepare-boot-inputs.py \
  --firmware "$HARMATTAN_ORIGINAL_FIRMWARE" \
  --output "$PWD/extracted/private-boot-inputs"
```

The destination must not exist. The output contains 109 original non-rootfs payloads (49,755,648 bytes) and `boot-inputs.json`. The 110th record describes the rootfs already handled by `prepare-guest.py`; it is not duplicated. Files use numeric record prefixes, retaining all repeated types and target metadata. In particular, the five variants of each CMT component and multiple device fields in a record must not be collapsed into one filename or target. The report retains hardware revision strings, including leading zeros, without selecting a hardware variant or KCI.

The payload types include 22 each of `cert-sw`, `2nd`, `xloader` and `secondary`, four `1st`, five each of `cmt-2nd`, `cmt-algo` and `cmt-mcusw`, one original kernel and one `ape-algo`. All payloads and the detailed manifest stay private. Container SHA-256 and checksum verification establish extraction integrity, not Nokia signature verification, device-specific identity or a complete trust chain. Software certificates in a distribution are not provisioned device certificates.

The independent bounded parser's field interpretation was cross-checked against [0xFFFF's upstream FIASCO reader](https://github.com/pali/0xFFFF/blob/master/src/fiasco.c), by pancake and Pali Rohár. It is not a flasher, does not execute an SDK installer, and does not mount or modify a guest disk.

## Restore the actual GP branch

Nokia's recovered OMAP3 model initializes SCM `general[0x20]`, physical `0x480022f0`, to `0x30f`: GP device type plus its SDK boot straps. The previous port did not map that address. New `--cocoa-interaction` builds provide the four-byte register and its little-endian byte lanes. Writes report an unsupported guest access; the rest of SCM, fuses and secure hardware are not supplied by this small mapping. The maintained patch is `qemu-9.1.3-n00-control-status.patch`, applied after SSI.

The existing [SSI diagnostic](device-services.md#ssi-controller-implementation) now checks this word and each byte lane in all three SSI modes. The new build also changes PR1.3 `/proc/cpuinfo` from `ES1.0-test` to `ES1.0-gp`; original SSI binding and validator netlink continue to work. It preserves the original GP model rather than selecting an HS identity to satisfy a driver check.

## Original-loader evidence and limits

The [validation record](boot-chain-validation.json) records a bounded, headless trial of the unmodified RX-71 revision `000` first-stage payload, SHA-256 `58f28e5e7754d804f52b4c258170c9fcb6b0b8b453e1b0bd446a9ff3896d9dd7`. Its own relocation constants identify SRAM base `0x40200000`. The experiment loaded it there with QEMU's generic loader, with no disk, network, invented ROM arguments or modified instructions. This tests one cold-loader entry, not a complete ROM handoff or a selected retail N9 hardware profile.

Before the register repair, the read at `0x4020019c` hit unmapped `0x480022f0` and the code took the non-GP SMC path at `0x402001cc`. Afterwards it takes the GP path at `0x402001d4` and executes conditional `SMC #0` at `0x402001d8`. At that earlier revision both trials encountered an unmapped monitor vector at `0x8`; neither is accepted as a boot. The missing monitor cannot be replaced by unconditional successful SMC returns.

The earlier revision passed its clean QEMU build, 345 host tests, CONTROL_STATUS/SSI checks and PR1.3 prerequisite diagnostic. The default SDK-kernel headless UI regression also passed Home, original Notes/keyboard, Calculator, animation and GPU checks. The isolated original BME regression passed with 8/8 levels and 100%, retaining its hardware/IPC-only scope. Cocoa windows, physical input and long sessions were not tested.

The required next layer is the compatible ROM/monitor execution and boot handoff, followed by original BB5 initialization and authenticated credential loading. The original `validator-init` calls `bb5_open` before its non-HS-board fallback and before loading resource-token policy. Consequently, restoring the GP strap alone cannot resolve missing `dsme::DeviceStateControl`. PA/PAFMT files, software certificates and bootloader files are inputs to that work, not evidence that it has already succeeded.

## Restricted GP cache monitor and UART repair

`HARMATTAN_N00_GP_CACHE_MONITOR=on` explicitly maps a small read-only monitor at reset MVBAR zero. It defaults to off; other values fail startup. It only accepts executed ARM `SMC #0`, service `r12=1`, from little-endian SVC mode. The service number is defined by U-Boot's `OMAP3_GP_ROMCODE_API_L2_INVAL` and its `omap_smc1` call path (included in the pinned QEMU source archive). QEMU's ARM cache-maintenance operations do not model a data-cache array, so DSB/ISB complete this cache operation without fabricating a security result.

The maintained assembly preserves r0–r14 and SPSR through the real ARM Monitor exception return. Banked `SP_mon` holds one scratch register; no caller stack is used. Other service numbers, HS `SMC #1`, Thumb, big-endian and non-SVC callers stop at `0x80`, without returning success. This is a cache-service subset, not a Nokia ROM image, a general secure monitor, PA verification or a BB5 implementation. Monitor recursion and other exception vectors are unsupported. The ROM must remain opt-in while boot handoff and the rest of ROM are absent.

The original loader then exposed an existing QEMU UART address error. The extended memory region starts at UART base + `0x20`, but read/write callbacks decoded its relative offsets as full UART offsets. Original UART3 soft-reset access at `0x49020054` and reset-status polling at `0x49020058` therefore hit the wrong registers. The patch restores the offset and passes the full physical address to the existing diagnostic 32-to-8-bit fallback. It retains the width warning and the original register/reset semantics.

Run the firmware-free checks against the new `--cocoa-interaction` build:

```sh
python3 -B scripts/harmattan-qemu/diagnose-boot-registers.py \
  --qemu "$QEMU" --output "$NEW_REGISTER_OUTPUT"
python3 -B scripts/harmattan-qemu/diagnose-gp-cache-monitor.py \
  --qemu "$QEMU" --output "$NEW_SMC_OUTPUT"
```

The SMC diagnostic requires `HARMATTAN_ARMEL_CLANG` (or `--clang`) and matching `llvm-objcopy` (or `--objcopy`). It assembles the maintained source, compares every ROM byte with the checked-in C header, executes register/flag preservation and repeated-call cases, and checks all rejection cases. The register diagnostic checks default/off/on/invalid settings, ROM write protection and reset, UART byte/halfword access, the word fallback, read-only state, soft reset and the adjacent 16550 TX region. Outputs must be new private directories.

With both changes, the unmodified GP cold loader returns from `0x402001d8` to `0x402001dc`, passes UART reset and writes the first serial character. It subsequently reads an absent ROM function pointer at `0x1432c` (table base `0x14000`, offset `0x32c`) from `0x40200608`, and branches to zero. The observed terminal `0x80` is then in **SVC**, not a rejected SMC in Monitor mode. The ROM API/transport and handoff contract remain to be implemented from evidence; no successful stub is supplied. Earlier pad-control writes are still unmapped. This cold-loader trial does not establish the retail operating-system boot path or validate KCI, certificates, modem firmware or service readiness. See `gp_cache_uart_phase` in the [validation record](boot-chain-validation.json) for current checks, separate from earlier results.

The current revision passed a fresh QEMU build, 348 host tests, all 11 ARM SMC cases and the boot-register checks. Its first final-build UI run failed on one Calculator-restore black RAM sample, while functional and host-graphics checks passed. An independent rerun using the same binary and unchanged validators passed with zero black samples. Both results are retained; this does not establish long-session stability or a cause for the first sample. The full original service graph, Cocoa window and physical input were not revalidated in this phase.
