# Experimental native Linux window

[简体中文](linux-native.zh-CN.md) · [Linux build and guest preparation](linux.md) · [Validation record](linux-native-validation.json)

This opt-in source path presents the original 480×864 Harmattan UI in a Godot 4.6.3 native window on Linux x86_64. QEMU 9.1.3 still runs ARM32 code under TCG; DGLES and Mesa OSMesa render the original Home, Calculator, Notes and Maliit. It extends the [bounded Linux port](linux.md), whose design, build and scoped board/render results addressed the initial investigation in [issue #3](https://github.com/YZune/harmattan-qemu/issues/3). It is not a Linux release package or a complete phone emulator.

## Design and scope

- `ports/linux-native-ui/` owns the Godot window, scaled framebuffer view, mouse/keyboard events and visible connection/error state. It does not recreate the guest applications.
- `run-linux-ui.py --mode live` starts the existing strict guest controller. `linux-live-bridge.py` exchanges local files with the frontend in an owned, private session directory. The controller alone owns QMP over stdio; there is no HTTP, WebSocket, VNC or QMP listener. Guest networking and audio are disabled.
- Each capture briefly pauses QEMU for a PPM screendump, resumes it, then exports PNG and verifies identical RGB pixels. Capture scheduling targets 18 Hz without catch-up bursts. The frontend polls and caps engine rendering at 30 Hz; neither target is a guest FPS claim.
- Only unpublished drag motions are coalesced. The final motion is flushed before release, keys, Back or Quit, preserving event order and timestamps. Controller identity and contiguous sequence checks prevent replay. Lost frontend heartbeat releases a held touch.
- Linux enables readiness-first System UI/Maliit polling only with `N00_UI_POLL_READINESS_FIRST=1`, exported automatically by the controller. Successful reports retain the required hashes, ownership, mapped-library and ABI checks, plus the existing readiness budgets and fault gates. The default macOS reporting path remains unchanged; nine synthetic scenarios verified its output byte-for-byte against the baseline.

The macOS Cocoa entry point and defaults are unchanged. This Linux work does not establish a macOS runtime regression pass.

## Build and launch

First complete [Linux dependencies, source builds, DGLES smoke and guest preparation](linux.md). Keep the selected build/runtime paths and the exact renderer reported by the smoke test. The historical renderer was `llvmpipe (LLVM 19.1.7, 256 bits)`; do not substitute it for a different local result. You also need a graphical desktop that can run Godot's GL Compatibility renderer and an [official Godot 4.6.3](https://github.com/godotengine/godot-builds/releases/tag/4.6.3-stable) executable available as `godot`. Other Godot versions and display environments require separate validation.

Run both commands from this repository root, as the same user. Choose a new absolute session path for every launch; the controller creates it. Do not reuse a previous session or share its files with another user. The example basename below can be changed, but both terminals must use the same path.

In terminal 1, with the build variables from the Linux guide still set:

```sh
export HARMATTAN_LIVE_SESSION="$PWD/extracted/linux-native-session-01"
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --mode live --live-session "$HARMATTAN_LIVE_SESSION" --timeout 1800
```

Wait until the controller has created the fresh session directory and its `events/` subdirectory, then launch terminal 2. The frontend fails closed if either directory is missing; do not create them yourself to bypass startup.

In terminal 2:

```sh
godot --path ports/linux-native-ui -- \
  --session "$PWD/extracted/linux-native-session-01"
```

The timeout is a bounded controller budget, including guest startup, not 30 minutes of guaranteed interactive use after Home appears. Live mode accepts 1–1800 seconds. Build/preparation time is separate. `--output` may select a fresh diagnostic output directory. The launcher rejects persistent-profile and prebuilt-package settings; this path uses a disposable qcow2 overlay and snapshots. Notes saved in the guest are discarded at exit. Keep the prepared base quiescent.

For detailed local timing, add `--metrics` to the Python command and after `--` in the Godot command. Metrics are optional and do not relax readiness or input validation. Status, input audit and terminal results remain separate from detailed timing; session files can contain typed text and guest pixels and belong outside Git.

## Input and clean exit

Wait for **Live** and a fresh guest image. A fresh startup heartbeat with frame counter zero means the controller is still starting, not that Home is ready.

- Mouse clicks and drags map to the original single-touch surface. Drag inward from the side margin for edge gestures. The **Back** button or **Escape** requests the original right-edge return gesture; it is not a guest hardware Escape key.
- Open a Notes document and its original UK English Maliit letter keyboard before host typing. Supported host input is ASCII letters (including Shift for case), Space, Enter, Backspace, comma and period. The bridge must recognize the visible letter layout. Use the onscreen keyboard for digits, other symbols or other layouts; unsupported/unrecognized input produces a visible error. This is coordinate-driven guest keyboard input, not clipboard paste, host IME integration or direct guest-file editing.
- Focus loss, stale status/frame data and input failures disable interactive input and release held touches where the controller is reachable. An acknowledgement means an event was handled, not that the intended application action succeeded.
- Use **Quit** or the window close control. The frontend requests controller cleanup and waits for acknowledgement and terminal status; a confirmed successful shutdown closes the frontend with exit 0. During startup, cancellation takes effect at the next bounded helper/serial checkpoint, not immediately inside a running step. Verify the launch result reports success, QEMU exit 0, clean graphics teardown and joined workers. A closed frontend alone is not proof of a clean guest exit.

## Failures and readiness

Missing/mismatched build inputs, an incorrect renderer, a reused/unsafe session directory, invalid frame data, sequence gaps or stale controller state must remain failures. Do not edit status files or bypass checks to force **Live**. On startup timeout, inspect the diagnostic `controller.log` and result JSON; provide the missing input or resolve the failed readiness gate, then use a fresh session. The launcher bounds the controller and cleans up its own process group on failure. If the controller becomes unavailable or fails, **Close** exits only the frontend with exit 2 and explicitly leaves cleanup unconfirmed. Retain the controller output and inspect its terminal result; do not treat the last displayed frame or a locally closed window as proof of a running or cleanly stopped guest.

## Recorded results and their limits

The [validation record](linux-native-validation.json) separates the historical private experiment from checks of the public integration. The private optimized run used native desktop mouse/keyboard events generated through OS UI automation. It passed Calculator `2+3=5`, a real window edge drag, Notes `Linux` → `Linu` → `Linux works`, save, Escape return and native Quit. All 66 input events were accepted; QEMU/controller exited 0 with zero counted graphics faults/rejections and all workers joined. An unchanged-source, fresh-cache repeat passed Calculator/reopen/clear/recalculate/edge-return/Quit with 80 accepted events. Base-image preservation was checked by metadata, not a new full disk hash. Five selected Calculator frames had identical RGB in the static-control region; that is a bounded consistency check.

The matched comparison uses the 30 seconds from first capture publication +5 s to +35 s while Home is idle:

| Observation | Baseline | Optimized |
| --- | ---: | ---: |
| New captures observed after frontend draw | 4.891 Hz | 17.974 Hz |
| Frontend CPU, one logical core = 100% | 503.771% | 74.417% |
| Controller CPU | 13.531% | 39.254% |
| QEMU CPU | 1.903% | 4.954% |
| Sum of those three processes | 519.205% | 118.625% |
| Publish to post-draw callback, median / p95 | 43 / 75 ms | 24 / 41 ms |

The repeat observed 17.898 Hz in the same idle window. These are sampled capture/transport and frontend callback measurements, not guest FPS, physical scanout or photon latency. CPU comes from cumulative process ticks with window-boundary interpolation; multithreaded CPU can exceed 100%.

The measured edge-drag release-to-controller-acknowledgement tail was 1,136 → 19 ms. The gestures followed the same route but lasted 806 and 500 ms, so this is not identical motion replay. Timing starts at the Godot input callback, not physical input. It shows the observed queue reduction in these gestures, not a hardware latency guarantee.

Startup was 160.596 s for the instrumented baseline, 107.062 s optimized and 105.471 s for the unchanged-source fresh-cache repeat. Earlier source versions took 161.215 and 131.403 s. The first optimized start partly overlapped a host test run; the repeat did not. Readiness, caches and host load vary, and frontend contention changed alongside hash-read ordering. These few runs do not isolate one optimization's effect or establish a fixed startup speedup. Nested timing spans must not be summed with their enclosing spans.

The historical 426-test host suite had 9 LeakSanitizer/ptrace failures, 4 Unix-socket permission errors and 7 skips; it was not an all-green run. Its 15 bridge and 5 polling tests passed, as did Godot parsing and 227 isolated synthetic frontend assertions. Those counts belong to the private experiment. Initial public-integration checks executed 453 host tests in 31.311 s, with 9 LeakSanitizer/ptrace failures, 4 Unix-socket permission errors, 1 missing-Clang error and 7 skips. Seven Godot wrapper tests passed, including 325 metrics-off and 324 metrics-on synthetic assertions, before an additional typing fix awaiting rerun. Publication inspection covered 370 files with zero errors, and shell syntax/diff checks passed. Final reruns and CI remain pending; these results must not be inferred from the historical counts. The full guest/native flow has not been rerun after publication-path cleanup because the prepared inputs are unavailable in that environment.

No claim is made for a Linux installer, persistent profiles, full retail boot/services, cellular, browser/network/audio/camera support, physical GPU acceleration, arbitrary applications/layouts, touch hardware, long sessions or full macOS regression coverage. Guest media, raw logs, screenshots and third-party binaries are not part of this source addition.
