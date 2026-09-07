# Boot-chain inputs and the GP control register

[简体中文](boot-chain.zh-CN.md) · [Device services](device-services.md) · [Kernel](kernel.md)

Full secure boot is still **BLOCKED**. This work prepares original boot/modem inputs and restores the missing GP `CONTROL_STATUS` mapping. It does not install a secure monitor, provision BB5 storage or grant service credentials.

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

Before the register repair, the read at `0x4020019c` hit unmapped `0x480022f0` and the code took the non-GP SMC path at `0x402001cc`. Afterwards it takes the GP path at `0x402001d4` and executes conditional `SMC #0` at `0x402001d8`. Both trials encounter an unmapped monitor vector at `0x8`; neither is accepted as a boot. The missing monitor cannot be replaced by unconditional successful SMC returns.

The clean QEMU build, 345 host tests, CONTROL_STATUS/SSI checks and PR1.3 prerequisite diagnostic completed successfully. The default SDK-kernel headless UI regression also passed Home, original Notes/keyboard, Calculator, animation and GPU checks. The isolated original BME regression passed with 8/8 levels and 100%, retaining its hardware/IPC-only scope. Cocoa windows, physical input and long sessions were not tested.

The required next layer is the compatible ROM/monitor execution and boot handoff, followed by original BB5 initialization and authenticated credential loading. The original `validator-init` calls `bb5_open` before its non-HS-board fallback and before loading resource-token policy. Consequently, restoring the GP strap alone cannot resolve missing `dsme::DeviceStateControl`. PA/PAFMT files, software certificates and bootloader files are inputs to that work, not evidence that it has already succeeded.
