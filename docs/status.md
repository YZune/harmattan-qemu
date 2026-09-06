# Status and validation boundaries

[简体中文](status.zh-CN.md)

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

The [package installer](applications.md) now transfers reviewed ARMEL packages into an explicit profile, preserves dependency failures and restores SDK graphics links after package triggers. The [application record](applications-validation.json) covers 277 host tests, all dependencies configured, restart and original Home with ownNotes, Filebox and FBReader installed. Individual application functions await native window validation.

Source launches now offer optional [sound output](audio.md) through a private PulseAudio server and Mac CoreAudio. The [audio record](audio-validation.json) covers 281 host tests, original guest libpulse PCM, GStreamer WAV, mute and the combined UI regression with audio enabled. This is separate from full Nokia audio hardware and policy emulation.

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
