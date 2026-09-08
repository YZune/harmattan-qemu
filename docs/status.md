# Status and validation boundaries

[简体中文](status.zh-CN.md)

The [boot-chain input and GP register work](boot-chain.md) restores CONTROL_STATUS and preserves 109 original non-rootfs payloads in a private preparation path. An opt-in GP cache monitor and UART offset repair now advance the original cold loader to its absent ROM function table; full ROM/BB5 execution and secure boot remain blocked.


An explicit [incoming-call simulation](call-simulation.md) now drives the original call UI and ringtone with synthetic call state. It is separate from cellular emulation and is disabled in normal startup. See its [validation record](call-simulation-validation.json). Its explicit locked mode retains the original green swipe animation; answer/reject and lock restoration passed functional checks, while the strict GPU gate still fails. See [combined validation](call-lockscreen-validation.json).

## Experimental compatibility

The research baseline was `621c7f7` (2026-09-05). These are recorded results from that workspace, not a promise for a different guest image or host toolchain.

| Area | Recorded result | Limit |
| --- | --- | --- |
| ARM64 host / ARM32 guest | Native QEMU, direct kernel boot, storage and framebuffer | Experimental N00 board, not complete OMAP3/N9 emulation |
| Original Home | Mapped desktop, original resources, touch scrolling | Minimal rescue startup, not the full product boot/service graph |
| Calculator | Launch, `2+3=5`, edge return and instance recovery | Does not establish arbitrary application compatibility |
| Notes and Maliit | Text entry, deletion, symbol layout, in-guest save and keyboard reopen | Original UK English layout; no persistence across snapshot runs |
| Compositor | Stacking/pixmap fixes, animation intermediate frames, display handoff | Sampled zero black frames are not an FPS or universal no-flicker guarantee |
| Statusbar | Original service and local clock/minute updates | Not real cellular, battery or device telemetry |
| Cocoa lifecycle | Cancel/confirm window close and Quit menu, clean worker shutdown | Dock menu was not directly exercised in the recorded UI audit |
| Input activity | Input acquisition, 8-second idle release, reacquisition and exit cleanup | No fixed performance multiplier promised |

The baseline recorded 220 passing host tests. The original reproduction logs include paths and runtime material outside this source distribution; this release carries the test/diagnostic code and a curated account of its scope, not all historical logs.

## Public source export validation

On 2026-09-05 the exported tree's 224 host tests passed (220 baseline tests plus four importer safety tests) on Apple Silicon macOS, including native geometry tests using a synthetic fixture. Host test success is separate from a guest boot or original artwork validation. Local socket restrictions required running the socket tests outside the development sandbox.

Additional release build/runtime checks are recorded in [release-validation.json](release-validation.json). Read each check's scope; an untested field is not a pass. GitHub Actions separately exercises source checks and host tests on macOS and Linux.

The macOS prebuilt preview has a separate [validation record](release-preview-validation.json), including relocation, private input import and the combined guest regression.

The [original-media preparation record](guest-preparation-validation.json) covers a complete fresh run from the two pinned SDK/firmware inputs, unchanged original hashes, a clean read-only filesystem check, 246 host tests and the published app's combined headless Home/Notes/keyboard/Calculator/transition regression. See [Get guest inputs](guest-inputs.md) for the supported preparation route.

The source now supports [original boot presentation](boot-animation.md) over unchanged startup checks. Its [validation record](boot-animation-validation.json) covers a clean native build, 257 host tests and visible Cocoa startup/input/exit. Existing downloaded preview apps require rebuilding to include it.

Explicit [user profiles](storage.md) now preserve saved guest files across launches. The [storage record](storage-validation.json) covers 269 host tests, a clean native build, system/home file checks across two boots, snapshot isolation and an original Notes note saved through native input and still visible after Cocoa quit/restart. The same change fixes the disabled-network path without relaxing host-error validators.

The [package installer](applications.md) transfers reviewed ARMEL packages into an explicit profile, preserves dependency failures and restores SDK graphics links after package triggers. The [installation record](applications-validation.json) covers dependency configuration and restart. The [daily application record](daily-applications-validation.json) covers ownNotes editing and Filebox copying. The later [reader record](reader-validation.json) adds a pinned FBReader 0.99.5 viewport adapter, 290 host tests, local EPUB reading and exact page/state restoration after a guest restart, with all three applications in one profile. These function checks use headless QMP input; physical Cocoa input, reader swipe navigation and the Add Book picker remain outside the passed scope.

Source launches now offer optional [sound output](audio.md) through a private PulseAudio server and Mac CoreAudio. The [audio record](audio-validation.json) covers 281 host tests, original guest libpulse PCM, GStreamer WAV, mute and the combined UI regression with audio enabled. This is separate from full Nokia audio hardware and policy emulation.

Audio-enabled UI startup now includes the original OHM resource manager. The [ringtone record](ringtone-validation.json) covers 294 host tests, original Settings Nokia tune playback/stop through the private CoreAudio output, and the combined headless UI regression. Other tones and physical audio quality remain untested.

Normal source startup now uses [actual readiness checks](performance.md) instead of fixed compositor/Home delays. The [performance record](performance-validation.json) covers 285 host tests, paired startup timings, early-input protection and the audio-enabled Home/Notes/keyboard/Calculator/transition regression. The change keeps the single Cortex-A8/512 MiB board and original animation timings; it does not establish a display FPS improvement.

Network-enabled UI launches now select software page compositing in the pinned original browser, with optional host CA trust. The earlier [browser record](browser-validation.json) covers 302 host tests, Web-icon startup, the Baidu HTTPS homepage, original keyboard entry, certificate rejection and the generated shortcut UI regression. The optional [basic web mode](networking.md#optional-basic-web-mode) adds a separate shortcut that disables webpage JavaScript; the original entry and default remain unchanged. The [basic mode record](browser-basic-validation.json) covers 306 host tests and Baidu's basic search results in a fresh guest. Search with JavaScript enabled and arbitrary modern sites remain unaccepted.

The new [original device-service experiment](device-services.md) restores SDK power devices and volatile CAL storage, disabled by default. Original BME hardware/IPC diagnostics are separate from complete power and cellular acceptance; Aegis/BB5 and SSI modem transport remain incomplete. The default SDK kernel also lacks DSME validator notifications.

The opt-in SSI controller now passes MMIO/PIO/GDD/IRQ tests and lets the original SSI/CMT/Phonet modules load. `phonet0` can be administratively enabled, but reports no ready link. See the [SSI validation record](ssi-validation.json) for the clean source build, BME and headless UI regression; there is no modem or security-chain acceptance.

The optional [PR1.3 kernel](kernel.md) now boots with 101 matching modules and the original Aegis implementation. Its [validation record](kernel-validation.json) covers 338 host tests, a clean Linux kernel build, validator netlink binding and original DSME reaching USER. BME integration is rejected for missing credentials, and MCE/CSD bus ownership fails. Full security and cellular services remain BLOCKED; new-kernel UI behavior is untested.

The optional [SDK battery desktop mode](device-services.md#optional-original-battery-in-the-desktop) now starts original BME before ContextKit subscription and preserves original NoNetwork semantics. It remains disabled by default and rejects persistent profiles. See the [UI validation record](ui-power-validation.json). The [bounded security audit](security-feasibility.md) found no verified matching GP backend in the inspected material; ROM and modem-peer expansion is paused.

The [original lock-screen integration](lockscreen.md) connects the Cocoa shell side key to the original standby clock and swipe-to-unlock UI. Its [validation record](lockscreen-validation.json) separates host geometry, guest input and visible Cocoa checks. This does not restore MCE or hardware suspend/resume.

## Open limitations

Native source builds now provide opt-in [SDK Ethernet networking](networking.md). The [validation record](networking-validation.json) covers a clean QEMU build, 259 host tests, guest DHCP/public DNS/HTTP, bidirectional content checks and the combined headless UI regression with networking enabled. Existing downloaded preview apps require rebuilding.

- Linux/Windows runtime ports, independent second-Mac validation and Developer ID signing/notarization. See the [prebuilt preview](releases.md) for the packaged runtime and its remaining guest-input requirement.
- Independent reproduction of the new original-media preparation route, support for additional media versions, and a redistributable guest baseline.
- Complete EGL/GLES coverage, SGX emulation, and arbitrary ARMEL packages.
- Full Upstart/Aegis/device services, cellular, camera, hardware audio routing, Wi-Fi/connection-manager integration, and accurate physical sensors.
- General save/restore, machine reset and suspend/resume compatibility.
- All applications, keyboard languages, rotations, accessibility, and long-running sessions.
- Splash composition with all handoff modes; splash remains disabled in the normal path.

A legacy GPU diagnostic with animation/activity disabled has a known failed Calculator identity check and illegal calls in the research record. The normal combined usability configuration subsequently passed. Do not report the legacy failure as a pass or infer all modes are equivalent.

## Reporting a result

Include commit, host architecture/OS, compiler, source and guest identifiers, exact command, display mode, and a concise observed outcome. Keep host tests, headless guest results, Cocoa results and human interaction separate. The [issue template](../.github/ISSUE_TEMPLATE/bug_report.md) requests these fields.
