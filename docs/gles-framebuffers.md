# Bounded GLES2 framebuffer marshalling

[简体中文](gles-framebuffers.zh-CN.md) · [Linux build and guest preparation](linux.md) · [Native Linux window](linux-native.md) · [Validation record](gles-framebuffers-validation.json) · [Architecture](architecture.md)

This experimental milestone adds framebuffer-object (FBO) and renderbuffer-object (RBO) calls to the existing ARM32 guest-to-host GLES2 bridge. It supports a bounded offscreen-rendering subset through DGLES. Raw-wire, original-library and a scoped native Linux interaction run passed; this is not a complete GLES2 implementation, SGX emulation or a claim of arbitrary application compatibility.

## Implemented surface

The maintained `qemu-9.1.3-n00-gles-render.patch` supplies `n00_gles_fbo.inc`. It marshals these 14 wire methods:

| Operation | Methods |
| --- | --- |
| Names and lifetime | `glGenFramebuffers`, `glDeleteFramebuffers`, `glGenRenderbuffers`, `glDeleteRenderbuffers` |
| Bindings and identity | `glBindFramebuffer`, `glBindRenderbuffer`, `glIsFramebuffer`, `glIsRenderbuffer` |
| Attachments and storage | `glFramebufferTexture2D`, `glFramebufferRenderbuffer`, `glRenderbufferStorage` |
| Status and queries | `glCheckFramebufferStatus`, `glGetFramebufferAttachmentParameteriv`, `glGetRenderbufferParameteriv` |

The existing `glGetIntegerv` path also handles `GL_FRAMEBUFFER_BINDING`, `GL_RENDERBUFFER_BINDING` and the bounded `GL_MAX_RENDERBUFFER_SIZE`. Scalar outputs and object-name arrays use checked guest-memory copies and little-endian wire values. The five-argument texture-attachment call uses the existing ARM stack ABI with an overflow-checked address calculation.

Each GLES context owns separate framebuffer/renderbuffer bookkeeping. Guest object names map to host DGLES names, so guessed guest names cannot expose or delete DGLES's private default framebuffer. Guest framebuffer zero selects the existing default surface; binding queries return guest names. Generated names and objects created by binding a nonzero name use the same limits. Sharing between contexts is outside this milestone's verified scope.

## Bounds and lifetime

| Resource | Bound |
| --- | --- |
| Live framebuffer names | 128 per context |
| Live renderbuffer names | 128 per context |
| Name-array count in one generation/deletion call | 0–128 |
| Renderbuffer dimensions | Each dimension at most 4096 and no greater than the backend's reported maximum |
| Renderbuffer storage reservation | 64 MiB per context, charged as width × height × 4 bytes |
| Attachment points | `GL_COLOR_ATTACHMENT0`, `GL_DEPTH_ATTACHMENT`, `GL_STENCIL_ATTACHMENT` |
| Nonzero texture attachment | `GL_TEXTURE_2D`, level zero |

The storage charge is a logical reservation policy, not a physical host-memory cap or a measurement of Mesa allocation. It excludes textures, driver metadata, padding and other graphics resources. Every supported renderbuffer format is charged four bytes per pixel. The accepted storage formats are `GL_RGBA4`, `GL_RGB5_A1`, `GL_RGB565`, `GL_DEPTH_COMPONENT16` and `GL_STENCIL_INDEX8`.

Deleting a renderbuffer removes its live guest name and detaches it from the currently bound framebuffer. An attachment in another framebuffer can retain the old host object and its full reservation. The reservation is released only when that retained object's last attachment disappears, for example through replacement, detachment or framebuffer deletion. Reusing the guest name creates a distinct object. The bookkeeping has space for 128 live renderbuffers plus up to 384 retained attachment objects; this does not increase the live-name or storage limits.

Generation preflights the complete output range and rolls back host allocations if allocation or the subsequent guest write fails. Invalid counts, targets, attachment enums, formats, dimensions and unsupported nonzero texture levels are rejected. Zero-object attachment calls detach, ignoring the unused object-specific target/level fields. A failed attachment does not release the previous renderbuffer reservation, and a failed resize does not spend or free reservation based only on the request. Parameter rejections preserve an earlier pending GL error.

## Verification profiles

Keep these profiles separate. Their validators require the selected markers, exact call/rejection/fault totals, real renderer identity, expected pixels and joined workers; a negative test's intentional rejections are not accepted in an ordinary UI run.

- The raw-wire `--render --fbo-api` profile exercises object creation, binding, queries, texture/depth and color/depth attachments, clear/readback, deletion and return to the default framebuffer. The shared FBO fixture checks 24 RGBA pixels with output guards in addition to the existing shader/texture/vertex and display checks.
- Adding `--negative` selects the dedicated malformed-input profile. It checks invalid guest pointers, counts, limits and parameters, output preservation and recovery. Its expected failures belong only to this profile.
- The original-library `--fbo-api` profile links against the pinned guest EGL/GLES libraries and runs in original Xorg. Run it separately with `--noxshm 0` for XShm and `--noxshm 1` for XImage. It checks mapped libraries and their identities, actual shared-memory usage, the same FBO fixture, and two display frames. `--shell-api` is a distinct, mutually exclusive profile.
- Host tests execute the maintained marshaller against a bounded fake GL backend with AddressSanitizer and UndefinedBehaviorSanitizer. They cover endian conversion, allocation rollback, lazy binding, limits, resize accounting, scalar output guards, context isolation, stack overflow rejection, deferred lifetime and name reuse. These tests do not replace real Mesa or guest execution.

The original guest library's known repeated `eglTerminate(NULL)` result remains explicitly checked by the public-library validator. That existing termination defect is separate from FBO behavior.

The final local Linux probe runs on 2026-10-10 produced these results:

| Profile | Wire calls | Swaps | Expected guest-memory faults | Expected parameter rejections |
| --- | ---: | ---: | ---: | ---: |
| Raw FBO | 177 | 4 | 0 | 0 |
| Raw FBO negative | 271 | 4 | 7 | 16 |
| Original libraries, XShm | 142 | 2 | 0 | 0 |
| Original libraries, XImage | 142 | 2 | 0 | 0 |

All four checked the 24 FBO RGBA pixels plus their existing display checks and joined all graphics workers. The negative profile's 23 intentional failures include both swapped framebuffer/renderbuffer bind targets and verify that those rejected calls preserve the bindings. These results used QEMU SHA-256 `3665576d27bf70b63cf94864f67e59ea246cbed8b76c6d01762e15f30bc6853e`; they do not establish native-window acceptance.

Run the host marshaller checks with Python 3.12 or newer, `patch`, and a `cc` compiler with working AddressSanitizer and UndefinedBehaviorSanitizer support:

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_gles_fbo_marshalling.py' -v
```

The local validation environment's ptrace restriction required `ASAN_OPTIONS=detect_leaks=0`. That run retained address/undefined-behavior checks but did not check leaks. Use the host's normal sanitizer settings where supported.

The final local host-suite run on 2026-10-10 did not pass: 512 tests produced four errors and seven skips, with no assertion failures. All four errors came from `test_arm64_splash` because the cloud sandbox denied AF_UNIX socket creation. The eight FBO marshaller cases and six scoped compositor-correction cases passed. This local result does not establish CI or macOS runtime acceptance.

## Reproduce on Linux

Complete the [Linux source build, DGLES smoke and guest preparation](linux.md) first, using a fresh source workspace for the changed patches. Keep `HARMATTAN_PORT_WORKSPACE`, `HARMATTAN_LINUX_BUILD`, `HARMATTAN_DGLES_ROOT`, the ARM compiler and `debugfs` selections from that guide. Use Python 3.12 or newer with Pillow. The commands below run from the repository root and use only disposable overlays of a quiescent prepared base.

Set `HARMATTAN_FBO_RENDERER` to the exact renderer independently observed in the successful DGLES host smoke. The value below is an example from the Linux guide, not a substitute for observing your own backend. Run the complete block together: its subshell scopes the library/display exports to these probes so they do not leak into a later Godot native-window launch.

```sh
(
set -eu
export HARMATTAN_FBO_RENDERER='llvmpipe (LLVM 19.1.7, 256 bits)'
export HARMATTAN_FBO_PREPARED="$PWD/extracted/guest-from-original-media-linux"
export HARMATTAN_GLES_WIRE_DIR="$HARMATTAN_LINUX_BUILD/../hw/arm"
export HARMATTAN_ADAPTATION_LIBDIR="$HARMATTAN_FBO_PREPARED/overlay/usr/lib"
export HARMATTAN_PUBLIC_ROOTFS="$HARMATTAN_FBO_PREPARED/pr1.3-rootfs-qemu-rescue.ext4"
export LD_LIBRARY_PATH="$HARMATTAN_DGLES_ROOT/objs-x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export LP_NUM_THREADS=2
export EGL_PLATFORM=surfaceless
sh scripts/harmattan-qemu/build-gles-guest.sh
sh scripts/harmattan-qemu/build-gles-public-guest.sh --fbo-api
export HARMATTAN_FBO_RUN="$(mktemp -d "$PWD/extracted/gles-fbo.XXXXXX")"
export MESA_SHADER_CACHE_DIR="$HARMATTAN_FBO_RUN/mesa-cache"
unset N00_GLES_TRACE_REJECTS

# Raw-wire positive and negative profiles, each with a fresh overlay.
for profile in render-fbo render-fbo-negative; do
    image="$HARMATTAN_FBO_RUN/$profile.qcow2"
    "$HARMATTAN_LINUX_BUILD/qemu-img" create -q -f qcow2 -F raw \
      -b "$HARMATTAN_FBO_PREPARED/harmattan-pr1.3.raw" "$image" 32G
    set --
    if [ "$profile" = render-fbo-negative ]; then set -- --negative; fi
    python3 -B scripts/harmattan-qemu/smoke-arm64-gles.py \
      --output "$HARMATTAN_FBO_RUN/$profile" \
      --probe "$HARMATTAN_PORT_WORKSPACE/guest-probes/smoke-gles-guest-$profile" \
      --render --fbo-api "$@" --renderer "$HARMATTAN_FBO_RENDERER" --timeout 300 -- \
      "$HARMATTAN_LINUX_BUILD/qemu-system-arm" -M n00-port-spike \
      -kernel "$HARMATTAN_FBO_PREPARED/zImage-2.6.32.26-qemu" \
      -append 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 hlt console=ttyS0,115200n8 omap3_die_id' \
      -drive "if=sd,format=qcow2,file=$image" \
      -snapshot -display none -no-reboot -nic none
done

# Original-library XShm (0) and XImage (1) profiles.
for noxshm in 0 1; do
    image="$HARMATTAN_FBO_RUN/public-$noxshm.qcow2"
    "$HARMATTAN_LINUX_BUILD/qemu-img" create -q -f qcow2 -F raw \
      -b "$HARMATTAN_FBO_PREPARED/harmattan-pr1.3.raw" "$image" 32G
    python3 -B scripts/harmattan-qemu/smoke-arm64-gles-public.py \
      --output "$HARMATTAN_FBO_RUN/public-$noxshm" \
      --probe "$HARMATTAN_PORT_WORKSPACE/guest-probes/smoke-gles-fbo-api-guest" \
      --fbo-api --noxshm "$noxshm" --renderer "$HARMATTAN_FBO_RENDERER" --timeout 300 -- \
      "$HARMATTAN_LINUX_BUILD/qemu-system-arm" -M n00-port-spike \
      -kernel "$HARMATTAN_FBO_PREPARED/zImage-2.6.32.26-qemu" \
      -append 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 hlt console=ttyS0,115200n8 omap3_die_id' \
      -drive "if=sd,format=qcow2,file=$image" \
      -snapshot -display none -no-reboot -nic none
done
)
```

The probe builders produce `smoke-gles-guest-render-fbo`, `smoke-gles-guest-render-fbo-negative` and `smoke-gles-fbo-api-guest` under the selected workspace's `guest-probes/`. The raw probe does not require a guest sysroot or libc; the public probe verifies pinned library inputs and reads the prepared rootfs without modifying it. The first loop runs both raw-wire profiles; the second runs both original-library exchange modes. All four runs use independent overlays and output directories.

Stop and inspect a failed command before continuing. These direct probes expect the unrotated 864×480 guest display; do not add the native UI launcher's `-rotate 270`. Each output directory must be new. The runners upload their helper into the snapshot, use QMP on stdio and mode-0600 serial FIFOs, and open no host control listener. Linux captures an authoritative PPM and exports a PNG only after verifying identical RGB pixels. Read the generated `result.json`, `serial.log` and `qemu-stderr.log` locally; keep guest images, executables, raw logs and machine-specific paths outside Git.

Without `--renderer`, the probe runners retain the existing `Apple` default and socket transport. This Linux path does not change macOS defaults, and macOS runtime has not been rerun for this milestone.

## Original compositor correction and native verification

A native Notes run first exposed a separate original-compositor defect: `MCompositeWindowGroup::init` calls `glBindFramebuffer` with `GL_RENDERBUFFER` as its target. The strict Quit gate correctly failed with one render rejection and zero graphics faults. The inspected `libmcompositor.so.1.1.3` has SHA-256 `e9fcdb50530076abce62aaae65f5116a71badc283c89111a0d5e38f13b4a8c1b`. This guest caller defect is distinct from adding the missing framebuffer wire methods.

The Linux-only `--compositor-fbo-fix` option selects a separate process-local preload helper. Build and startup checks pin the full original library hash; the helper checks the loaded function's entry and call-site instructions. It changes the target to `GL_FRAMEBUFFER` only when the bad target comes from the exact `init+0x74` return address. Other calls pass through unchanged, and an identity/ABI mismatch fails closed. The original library binary and the bridge's wrong-target rejection behavior remain unchanged. The option is off by default and does not change macOS defaults.

With the [native window prerequisites](linux-native.md#build-and-launch) satisfied, use the exact renderer from your DGLES smoke and launch:

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --mode live --compositor-fbo-fix \
  --frontend "$(command -v godot)" --timeout 1800
```

The guarded native run on 2026-10-10 passed with both `guard_observed=true` and `callsite_fix_observed=true`. OS desktop events through the actual Godot window exercised Notes entry/save of `Linux works AaZz`, new/cancel/new with `Fbo works`, Escape to Home, draft reopen and saving both notes, mouse edge returns, Calculator `2+3=5`, and native Quit. The input audit recorded 103 events: 102 accepted and one automatic release cancelled by Quit priority, not a typing failure.

QEMU, the controller and Godot all exited with code zero; the frontend stopped naturally. The graphics summary recorded 14,116 calls, 161 swaps, zero faults, zero render rejections and joined workers. Prepared-base metadata stayed unchanged; full base hashes were not recomputed for this run. This is bounded native interaction and lifecycle evidence, not physical input latency, display FPS, performance improvement, persistent storage or long-session acceptance. See the [validation record](gles-framebuffers-validation.json) for the exact counters and separate failed/passed stages.

## Rejection diagnostics and remaining limits

For a targeted diagnosis, set `N00_GLES_TRACE_REJECTS=1` on the QEMU/controller invocation. It emits at most 64 rejection-detail lines plus a suppression notice. Each line contains the client, API, ABI, call number, GL error and saved `r0`–`r3` values. It does not read additional guest memory, consume the pending GL error or relax the strict rejection/fault gates. The switch is presence-based: unset it to disable tracing; setting it to `0` still enables it. Normal exact-log probe validation should run with the switch unset.

Cube-map attachments, nonzero texture levels, extension formats, multisampling, shared-context semantics, arbitrary applications and long-running stability remain outside the accepted scope. There is no new release-package, CI or macOS runtime acceptance from this work.
