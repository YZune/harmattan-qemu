# Startup and responsiveness

[简体中文](performance.zh-CN.md) · [Building](building.md) · [Validation](performance-validation.json)

Normal source launches and the combined usability regression now wait for actual compositor and Home readiness. The old unconditional compositor/Home sleeps are replaced by X11 ownership, original window identity and geometry, real compositor initialization events, and a nonempty Home frame that remains unchanged for five seconds. The original scrollbar must finish fading. The separate five-second settled phase, clock masking, input guard, executable identities, graphics error checks and animation validators remain in place. A missing or unstable desktop fails; it is not reported as a fast startup.

`HARMATTAN_UI_STARTUP_WAITS=ready` selects this path; `fixed` retains the former 8-second compositor and 25-second Home waits for comparison. Historical diagnostics keep `fixed` unless explicitly overridden. The boot movie only covers startup; it does not make the guest faster.

## Reproduce a bounded comparison

Keep the same native build, guest inputs and tool selections from the build guide. Close other emulator runs first, leave the user profile unset, and run one guest at a time:

```sh
unset HARMATTAN_USER_PROFILE
for waits in fixed ready fixed ready fixed ready; do
  HARMATTAN_UI_STARTUP_WAITS="$waits" HARMATTAN_UI_NETWORK=off \
    HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-arm64-ui.sh --startup-headless-diagnostic
done
```

Each run creates an independent disk snapshot and exits after the normal interactive readiness checks. Compare `startup_wall_seconds` in its `ui/ready.json`; `phases` and `startup_observations` explain the waits. This timer starts with the QEMU process, excluding source/helper builds and disk preparation. It includes diagnostic observations. Guest memory is recorded in the final serial report. The headless result does not measure Cocoa presentation, physical input latency, cold host filesystem caches or a different Mac.

The paired measurements, exact runtime identity and regression scope are recorded in [performance-validation.json](performance-validation.json). A startup improvement does not establish a higher animation FPS or faster execution inside every application.

On the recorded M5 Max, three alternating pairs produced:

| Wait mode | Median startup | Range |
| --- | --- | --- |
| `fixed` | 68.839 s | 68.662–69.391 s |
| `ready` | 51.464 s | 51.441–51.677 s |

The median reduction was **17.375 seconds (25.24%)**. The separate audio-enabled regression opened original Notes in 2.493 seconds and observed a median 0.220-second key response in guest RAM. That key measurement includes a 120 ms press and sampling overhead; it is a current observation, not a before/after input improvement.

## CPU frequency and memory

This board currently accepts exactly **512 MiB**, one **Cortex-A8**, and runs the ARM32 guest through TCG on the native ARM64 host. See the maintained [board patch](../ports/qemu-n00/qemu-9.1.3-n00.patch). `-m 1G` and additional vCPUs do not fit this board model. More RAM would first require compatible SDRAM mapping, boot information and guest-kernel validation.

TCG is not cycle-accurate hardware simulation. Changing a virtual clock or an instruction-counting ratio does not give the guest more host execution capacity; it can change device timing. The [QEMU TCG documentation](https://www.qemu.org/docs/master/devel/tcg-icount.html) explains that distinction. This change does not alter CPU clocks, guest RAM, animation duration or the original UI resources.

The observed Home baseline has substantial free guest memory and no swap. Extra RAM has no demonstrated benefit for that workload. Larger application working sets may behave differently and need their own pressure measurements. Further response work should use the existing input/framebuffer and CPU probes to identify execution, graphics-copy or service-wait costs. Those probes report sampled guest frames, not physical display FPS.

Existing downloaded preview applications do not acquire source changes automatically. This milestone validates the selected native source runtime; updated prebuilt packaging, native input latency and long sessions are separate checks.
