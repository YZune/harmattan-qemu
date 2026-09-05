# N00 forward port for QEMU 9.1.3

[简体中文](README.zh-CN.md) · [Build](../../docs/building.md) · [Architecture and patch order](../../docs/architecture.md)

This directory contains the maintained patch series and optional Cocoa view code. Apply the series through `scripts/harmattan-qemu/build-arm64-port.sh`; the normal interactive configuration is `--cocoa-interaction`.

The machine is `n00-port-spike`: experimental OMAP3/N00 direct boot, storage, DPI display, limited GLES, and MXT input. Read [status](../../docs/status.md) for compatibility boundaries and [sources](../../docs/sources.md) for Nokia/QEMU provenance and license choices.

The [DGLES patch](../dgles2/README.md) applies to its own source archive. [Device artwork](skins/README.md) is optional, user-supplied, and excluded from this release.
