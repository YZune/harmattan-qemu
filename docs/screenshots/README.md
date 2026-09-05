# Runtime screenshots

[简体中文](README.zh-CN.md) · [Project](../../README.md)

These three PNGs are unedited captures from the clean-build guest regression on 2026-09-05. They show original ARM Harmattan software executing inside QEMU on an Apple Silicon Mac.

| Capture | What it shows | Original output filename |
| --- | --- | --- |
| [home.png](home.png) | Original Home launcher, including partially visible next-row icons | `settled.png` |
| [calculator.png](calculator.png) | Calculator after the diagnostic entered `2 + 3 =`, displaying `5` | `calculator-sum.png` |
| [notes-keyboard.png](notes-keyboard.png) | Notes after typing `Qemux` and deleting the last character, with the original Maliit keyboard and word suggestion | `keyboard-deleted.png` |

The Notes content is test input. No account data or personal notes were used for these captures. The statusbar is the original UI; its battery and cellular indicators do not represent real simulated device services.

## Capture provenance

- Host: Apple Silicon ARM64, macOS 26.6.2.
- Emulator: clean QEMU 9.1.3 build with the port's Cocoa-interaction support; this run selected `-display none`.
- QEMU SHA-256: `0454a1243cf6ca38924bf818b4761e14c8100404d753d19c9bd49201fe8c68f5`, matching [release-validation.json](../release-validation.json).
- Guest: PR1.0-era emulator kernel/adaptation with prepared PR1.3 userspace, as described in [Building](../building.md).
- Run identifier: `run.E1swqs/ui`; QEMU exited with status 0 after the joint usability diagnostic.
- Capture: the `capture()` helper in [diagnose-arm64-shell.py](../../scripts/harmattan-qemu/diagnose-arm64-shell.py) pauses guest execution, exports PNG/PPM through QMP `screendump`, then resumes it.
- Files: 480 × 864 pixels each, copied byte-for-byte from the original outputs. No cropping, compositing, skin artwork, retouching, or generated replacement UI was added.

These are QEMU guest-surface screenshots, not captures of a macOS window or the separate browser prototype. They demonstrate those guest states. They do not measure animation FPS, input latency, macOS window rendering, or physical mouse interaction. Static screenshots do not establish compatibility for other applications.

After completing the build and input setup, run:

```sh
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

Look for the three original filenames in the new run's `ui/` directory. Timestamps and runtime state may differ; a rerun is not expected to reproduce identical screenshot hashes. The publication check pins the current reviewed bytes in [check-public-tree.py](../../scripts/check-public-tree.py). Replacing a screenshot requires inspecting the new capture, updating its provenance, and updating that hash explicitly.

## Attribution

The depicted interface, icons, typography, and trademarks are the original work of Nokia and their respective rights holders. These captures document the emulator's behavior. The project's GPL notice does not relicense the depicted content; see [NOTICE](../../NOTICE). No firmware, font file, or standalone theme asset is supplied by this gallery.
