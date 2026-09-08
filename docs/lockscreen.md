# Original lock screen and the side key

[简体中文](lockscreen.zh-CN.md) · [Build and run](building.md)

Fresh Cocoa interaction builds connect the lower right-hand side key in both the `black` artwork and code-drawn `frame` shell to the original Harmattan lock UI. Wait for `READY` before pressing it.

1. Press the side key to lock the screen and show the original standby clock.
2. Press it again to show the original wallpaper, date and unlock screen.
3. Swipe across the screen to unlock and return to the current application. A tap or short, cancelled swipe keeps the screen locked.

The volume rocker above the key is unchanged. Glass and screen edges retain their existing touch routing, while the rest of the body still drags the window. The key follows the window's scale and letterboxing.

Normal interactive startup enables the integration. Set `HARMATTAN_UI_LOCKSCREEN=off` to disable it. Select `HARMATTAN_UI_SKIN=frame` for a shell that requires no external artwork. An older QEMU binary needs rebuilding; changing the launcher alone does not add the button.

```sh
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
HARMATTAN_UI_SKIN=frame sh scripts/harmattan-qemu/run-arm64-ui.sh

# Independent snapshot; original UI state and real guest touch input, then exit.
HARMATTAN_UI_LOCKSCREEN_TEST=on \
  sh scripts/harmattan-qemu/run-arm64-ui.sh --startup-headless-diagnostic
```

The integration currently requires upright portrait mode, original System UI and readiness-based startup. The bounded diagnostic rejects persistent profiles. Interactive launches can select a [user profile](storage.md); lock cycles in persistent profiles have not been separately validated.

## Implementation and limits

The Cocoa button posts one complete request to the launcher's private per-run mailbox. Startup and shutdown disable that mailbox; rapid clicks coalesce while a request is pending. The existing controller invokes a small guest helper through its own serial connection. It verifies the original `sysuid`, the Nokia screen-lock plugin, D-Bus ownership and the actual X11 window state, then requests `tklock_open` mode 6 (standby clock) or mode 5 (unlock screen). Original guest UI, resources and swipe handling remain in `sysuid`.

This is a screen-lock UI integration in the rescue desktop. It does not restore MCE, a PIN/device security lock, automatic idle locking, physical power-key GPIO events, display power savings, or hardware suspend/resume. The standby clock is the original low-power **UI mode**; QEMU keeps running. Native full-display-off mode is not selected. The separate [locked-call experiment](call-simulation.md#locked-incoming-calls) connects original call events to this UI. General notification wake-up remains outside the accepted scope.

On the SDK 480 × 864 surface, the wallpaper lock view currently leaves a 10-pixel white strip at the bottom; the standby clock fills the surface. This rendering difference remains open.

See [validation](lockscreen-validation.json) for the checks actually run. Host hit-testing, headless guest input and visible Cocoa interaction are separate evidence.
