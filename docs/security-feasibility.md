# Bounded security feasibility audit

[简体中文](security-feasibility.zh-CN.md) · [Device services](device-services.md)

The current decision is to pause ROM/cold-loader and modem-peer expansion. Preserve the existing opt-in experiments and prioritize the usable original desktop. The material audit below found no verified GP/SDK backend that can initialize the retail PR1.3 security graph unchanged. This is a scoped negative result, not proof that no such historical implementation exists.

## Material checked

| Original input | Observation | Consequence |
| --- | --- | --- |
| PR1.3 source DVD, `aegis-enabler 0.0.32+0m8` | `validator-init.cpp` calls `platsec_open`; `platsec.c` calls `bb5_open(NULL)` first. Non-HS development-board handling exists later in the RDC checks. | The development-board comment does not provide a successful BB5 open or credential initialization. |
| Same source DVD inventory | Aegis enabler/crypto, certificate management, builder, credentials and resource-token sources are present. No `libbb5`, `platsec` or `libcal` package-name match was found in this inventory; the enabler depends on `libbb5-dev` and `libcal-dev`. | The provided DVD does not supply the missing backend's implementation and headers under those package names. |
| Original DFL61 `1.2011.22-5.S` SDK disk, read-only extraction from a new raw derivative | Installed `libbb5-0` and `libbb5-secbins` are `2.5.36+0m6`. Package metadata describes the `/dev/omap_sec` interface; library strings and `bb5_open` disassembly retain the device-open path. | The SDK library is not evidence of a software security backend independent of that device. No cross-version library replacement was attempted. |
| Same SDK disk | No `aegis-enabler` package entry; `/etc/init/aegis.conf` mounts securityfs and optionally runs `libcreds-audit`, without calling retail `validator-init`. | SDK startup cannot be equated with retail PR1.3 trust-chain initialization. The original SDK image was inspected, not booted in this audit. |
| Original kernel source and earlier prerequisite runs | `sec.c` rejects KCI zero before registering the security device. The `hs.c` backend requires HS/EMU state and secure RPC/PA verification. | Neither creating a device node nor changing the GP strap establishes a matching backend. See [kernel evidence](kernel-validation.json). |

The extracted SDK `libbb5.so.0.0.0` SHA-256 is `034a7dc91736bbc91cd170c8fb811e0cdfd627d17b15122924848dd760844e91`; the inspected retail counterpart is `965ce75b1bc2217a37cf525ecfc3f830cbd66431d7e2533b5551b914d6cda208`. Private disks, extracted binaries and logs stay outside Git. This audit changes no firmware, credential policy or security check.

## Resume criteria

Resume security implementation only with an attributable, matching backend or documented handoff that can be tested through original interfaces: successful `bb5_open`, original validator initialization, required DSME/MCE/CSD credentials and actual D-Bus ownership. Preserve negative tests and retain failures. An unrelated SDK library, a PA filename, a guessed KCI, a GP cache SMC return or a running daemon alone does not meet this threshold.

Cellular still additionally requires a modem/ISI peer, SIM state and registration. Until those prerequisites are evidenced, retain the original NoNetwork UI and report full services as blocked. The optional BME desktop mode is independently useful and remains explicitly limited to the SDK's virtual power hardware.
