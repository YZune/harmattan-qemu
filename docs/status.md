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

## Open limitations

- Linux/Windows runtime ports and an independently movable macOS application bundle.
- End-to-end guest disk reconstruction from original media and a redistributable guest baseline.
- Complete EGL/GLES coverage, SGX emulation, and arbitrary ARMEL packages.
- Full Upstart/Aegis/device services, cellular, camera, audio, networking, and accurate physical sensors.
- General save/restore, machine reset and suspend/resume compatibility.
- All applications, keyboard languages, rotations, accessibility, and long-running sessions.
- Splash composition with all handoff modes; splash remains disabled in the normal path.

A legacy GPU diagnostic with animation/activity disabled has a known failed Calculator identity check and illegal calls in the research record. The normal combined usability configuration subsequently passed. Do not report the legacy failure as a pass or infer all modes are equivalent.

## Reporting a result

Include commit, host architecture/OS, compiler, source and guest identifiers, exact command, display mode, and a concise observed outcome. Keep host tests, headless guest results, Cocoa results and human interaction separate. The [issue template](../.github/ISSUE_TEMPLATE/bug_report.md) requests these fields.
