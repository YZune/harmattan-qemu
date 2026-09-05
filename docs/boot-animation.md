# Original boot presentation

[简体中文](boot-animation.zh-CN.md) · [Building](building.md)

## Why startup checks remain

The native launcher starts a minimal rescue session with original Xorg, theme service, System UI, compositor, keyboard and Home. Its bootstrap/theme/compositor/home/settled/final phases both start those components and validate them. The controller verifies executable identities, GPU output, stable Home pixels and the input barrier before printing `READY`. The intermediate frames do not need to be shown to the user. This change preserves all validators and existing waits (including 8 seconds for the compositor, 25 seconds for Home and 5 seconds for settling); it is a presentation change, not a measured startup speedup.

## Original media and behavior

The supported PR1.3 root filesystem contains:

- `/usr/share/MProgressIndicator/themes/mprogressindicator.conf`, selecting `opengl`.
- `/usr/share/MProgressIndicator/themes/opengl/MainAnimation_LowNoise.mp4`: 449,012 bytes, RIFF/AVI container despite its filename, MPEG-4 video at 854 × 480, 24000/1001 frames per second, approximately 4.2 seconds, including an MP3 audio track.
- `/etc/init/xsession/mprogressindicator.conf`: starts the original X11 `MProgressIndicator` and stops it on `DESKTOP_VISIBLE`.
- `/etc/init/xsession/mpi-animation.conf`: signals that same process to start the Nokia animation.

The movie SHA-256 is `19e311e44e102c84d75fe921f6af3af212173a86cbb549714ee1118b8d4ea40a`. No movie, image, logo or decoded frames are included in the source or application package. The launcher reads that one resource from its private raw disk clone and verifies the exact bytes, then rewraps the unchanged MPEG-4 packets in a silent MP4 container for AVFoundation. This uses Python standard-library code, without transcoding or an extra decoder. The bounded read-only ext4 reader supports the prepared PR1.3 layout, rejects unsupported mapping/features and never follows symlinks, mounts a filesystem or replays a journal. Its structures follow the [Linux ext4 documentation](https://www.kernel.org/doc/html/latest/filesystems/ext4/).

The Cocoa overlay displays the movie's first frame during early startup, plays once at original speed when Home starts, then holds the final frame while validation finishes. It follows display rotation and preserves the movie aspect ratio with black margins. Playback is muted: guest audio hardware remains unimplemented. This reuses the original visuals through AVFoundation; it does not run the original MPI process or restore retail Upstart/device services.

The guest framebuffer keeps rendering behind the overlay. QMP captures still contain real guest pixels. Only after every existing startup check passes does the controller request a reveal, wait for Cocoa to acknowledge it, and release the existing guest input barrier. Movie completion alone cannot enable input or report readiness. Failures retain the run logs and fail the launch rather than displaying a successful desktop state.

## Build and diagnose

Rebuild `--cocoa-interaction` from fresh sources; the last maintained patch adds the Cocoa overlay and system AVFoundation/CoreMedia frameworks. No additional user-side decoder, Python package, debugfs or artwork is required for app launches. The prebuilt packager includes this code when rebuilding a release; existing downloaded applications are not modified.

Normal interactive startup enables the overlay. `HARMATTAN_UI_BOOT_ANIMATION=off` exposes the intermediate framebuffer for diagnosis; a rebuilt app also accepts `run --no-boot-animation`. Bounded diagnostics retain their existing presentation. Application `HARMATTAN_UI_SPLASH` is separate and stays off.

The run's `ui/boot/` contains the private extracted movie, phase request and native acknowledgement files. `ready.json` records the movie hash and successful desktop reveal. The runtime movie is a container-only derivative; `playback_sha256` identifies it separately from the original resource. These files are local runtime evidence and must not be published. Host tests use a synthetic filesystem and code-generated video, with negative cases for malformed metadata, changed resources and premature reveal.

The [validation record](boot-animation-validation.json) documents a clean native build, 257 passing host tests, identical original/rewrapped video packets and decoded frames, and a visible Cocoa startup followed by native mouse `2+3=5` and normal Quit. It does not establish a startup speedup, full product boot or validation of a newly packaged app.
