# Architecture and patch ownership

[简体中文](architecture.zh-CN.md)

## Boundaries

| Layer | Ownership | Main source |
| --- | --- | --- |
| Host emulator | QEMU 9.1.3 plus forward-ported Nokia N00 devices | `ports/qemu-n00/` |
| Host graphics | Nokia DGLES source with Cocoa offscreen FBO adaptation | `ports/dgles2/` |
| Guest kernel and adaptation | User-supplied PR1.0 emulator kernel and graphics ABI | External inputs |
| Guest product software | User-supplied PR1.3 original libraries and applications | External inputs |
| Guest compatibility | Small, scoped helpers loaded into disposable runs | `scripts/harmattan-qemu/*-guest.c` and guest scripts |
| Validation | Host unit tests, QMP input, guest identity and pixel checks | `scripts/harmattan-qemu/tests/` and diagnostic scripts |

`n00-port-spike` is an experimental machine. It directly boots an ARM32 kernel; it does not recompile Harmattan for AArch64. The display follows Nokia's generic DPI path, not the retail DSI panel transport. Power behavior includes direct-boot presets and limited idle compatibility, not a complete power-off/resume model.

## Maintained QEMU patch order

The prefix below is `qemu-9.1.3-n00`. The builder selects only the appropriate optional stages for each mode.

| Order | Suffix | Purpose |
| --- | --- | --- |
| 1 | `.patch` | Board, SDRC, MMC, ARM boot, OMAP DMA |
| 2 | `-display.patch` | I²C, TWL, DSS and framebuffer decoding |
| 3 | `-gles.patch` | Guest graphics protocol and host worker bridge |
| 4 | `-gles-render.patch` | Limited GLES2 shader/texture/buffer drawing |
| 5 | `-gles-public.patch` | Original public EGL/GLES lifecycle |
| 6 | `-gles-shell.patch` | Calls required by original Qt/Home |
| 7 | `-input.patch` | MXT/GPIO and single-touch input |
| 8 | `-portrait.patch` | Display rotation and input transform |
| 9 | `-idle.patch` | WFI and limited clock/power compatibility |
| 10 | `-profile.patch` | Optional timing instrumentation |
| 11 | `-scanout-probe.patch` | Optional refresh experiments |
| 12 | `-activity-probe.patch` | Optional Cocoa activity experiment |
| 13 | `-interaction-activity.patch` | Input activity acquisition and expiry |
| 14 | `-n9-skin.patch` | Optional host view and edge input geometry |
| 15 | `-cocoa-shutdown.patch` | Asynchronous AppKit termination and cleanup |
| 16 | `-n9-frame.patch` | Original code-drawn frame for prebuilt distribution |
| 17 | `-boot-animation.patch` | Host presentation of the user's original boot movie |
| 18 | `-network.patch` | SDK SMC91C111 Ethernet on GPMC CS1/GPIO54, with SLIRP |
| 19 | `-storage-shutdown.patch` | Defer Cocoa profile exit until the controller flushes guest files |

The normal `--cocoa-interaction` build includes the idle/input activity path and the host view/shutdown code. It does not require artwork. The DGLES patch applies to a different source archive; never apply it to the QEMU tree.

## Guest graphics and UI

Original guest EGL/GLES libraries call the old kernel graphics interface. The QEMU bridge decodes the supported call subset, copies bounded guest memory, and executes host graphics work through DGLES. This is not a full PowerVR SGX implementation or complete EGL/GLES conformance.

Original Xorg, Qt, Home, and compositor remain in the guest. Small helpers adapt verified matrix, pixmap, stacking, handoff, and orientation behavior. ABI-sensitive helpers pin the guest library hashes; a different image requires new source/ABI verification. The normal path retains original animation transforms and timing, while splash remains disabled.

The [boot presentation](boot-animation.md) is a separate Cocoa overlay. It reads the original movie from the private disk clone and leaves guest pixels, QMP captures and startup validators intact. It does not enable application splash composition or restore the complete retail boot/service graph.

## Changes made for the public source distribution

- No-skin default; the build accepts an absent optional artwork file.
- Kernel and main guest disk can be selected through environment variables.
- Guest compiler/debugfs selection no longer assumes one developer's IDE installation.
- Skin geometry tests use a synthetic transparent image instead of redistributing artwork.
- Explicit input import/check tools and paired English/Chinese entry documents.

No original firmware or existing research checkout is modified by exporting this repository.
