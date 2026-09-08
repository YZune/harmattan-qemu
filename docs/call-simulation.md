# Simulated incoming calls

[简体中文](call-simulation.zh-CN.md) · [Building](building.md) · [Sound output](audio.md)

This explicit source-launch mode drives the original PR1.3 `call-ui` with synthetic incoming calls. It presents the original caller page, answer/reject controls and active-call timer. The caller is labelled **N9 simulation**. No telephone account, SIM, modem or microphone is used.

With the normal [prepared inputs and ARM helper tools](building.md) available:

```sh
# Separate Cocoa session; automatically presents one simulated incoming call.
sh scripts/harmattan-qemu/run-call-simulation.sh

# Visual interaction without sound or the optional PulseAudio dependency.
HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-call-simulation.sh

# Bounded snapshot with QMP button actions and private ringtone output checks.
sh scripts/harmattan-qemu/run-call-simulation.sh --headless-diagnostic

# Start locked, receive a call, swipe up from the green prompt, then answer.
sh scripts/harmattan-qemu/run-call-simulation.sh --locked

# Combined locked-call diagnostic without the optional audio dependency.
HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-call-simulation.sh --locked-headless-diagnostic
```

The dedicated entry enables private [PulseAudio output](audio.md) by default, including the SDK Ethernet transport it needs. Normal emulator startup keeps call simulation disabled. Existing local launcher selections can be reused with `HARMATTAN_UI_CALL_SIMULATION=on`; persistent profiles are refused. This experiment needs the source helper builder and is not included in previously downloaded prebuilt previews.

Wait for `READY` before interacting. Use the green answer button to enter the original call screen, or the red button to reject. The ringtone mute button stops the tune without answering. Hang up with the red button on the active-call screen. Return to Home with the usual edge gesture and open the separate **Simulate call** icon to trigger another call. Repeated requests while a call is pending or active are rejected. Closing the emulator ends the disposable session.

This is a runnable experiment: state and audio checks passed, but the repeated-call diagnostic still emits a GPU texture warning, so full graphics acceptance has not passed. The diagnostic retains its nonzero exit and does not accept the warning as clean.

## Implementation and limits

A small ARM helper implements the subset of the original Telepathy `StreamedMedia`, `Group`, `Hold`, Account and Connection interfaces used by this presentation. The original Ring account/object names exist only on a separate D-Bus instance, user-only in ordinary mode. The original system bus and NoNetwork state remain unchanged. The helper does not start Ring, CSD, Mission Control, a SIP registration or a media engine.

The private bus also runs the pinned original GConf daemon with a copied configuration directory. Its service declaration is necessary for the old client's `StartServiceByName`, even with an existing daemon owner. This preserves the original Blanco theme selection; a missing configuration service would otherwise select `base` and render red missing-image markers. The call program uses its original `-software -local-theme -graphicssystem raster` options to select a software viewport. The default system configuration and all application/theme binaries stay unchanged. The daemon is explicitly started, identity-checked and stopped with the session.

For the effect, the helper receives the original call UI's NGF ringtone requests and plays the user's original `Nokia tune.mp3` through guest GStreamer and the private output server. It loops until mute, answer or call end. This implements the requested simulated feedback; it does not restore the complete original NGF policy or physical sound routing. Active-call audio, microphone mute, speaker routing, DTMF, call waiting, contact matching, missed-call history are outside the accepted scope. The timer represents simulated call state.

The diagnostic checks pinned UI/backend/configuration processes, state transitions, stale-channel and invalid-request rejection, original button pixels, missing-resource markers, and a separate four-context GLES lifecycle. The existing desktop GPU validator is unchanged; faults, rejects, warnings, missing contexts and invalid teardown still fail. Audio-enabled diagnostics record about 32 seconds from the private output monitor and check both the full sample and its tail. This is software output evidence, not an acoustic or physical-input measurement. See the [validation record](call-simulation-validation.json) for the checks actually run.

## Locked incoming calls

`--locked` enables the separate lock-call adapter and shows the standby clock before the first call. Original `sysuid` presents the caller, status and green **Swipe up** prompt, retaining its original entrance, breathing and swipe animations. Swipe up to reveal the original answer/reject page; the swipe itself does not answer. This two-step interaction follows the [Nokia N9 instructions](https://devices.vodafone.com.au/nokia/n9/basic-use/answer-a-call/). This simulation entry restores the pre-call standby-clock or wallpaper-lock mode when the call ends.

Original `call-ui` runs on the private bus and the original lock UI on the desktop bus. A guest root relay forwards only `call` events through `insertEvent`, `removeEvent` and original lock callbacks, checking sender process identities. The desktop policy grants root send access to only those two methods and is removed at shutdown; original Aegis policies remain. The MCE name on the private bus provides only lock-state queries/signals backed by actual validated X11 window state. Other device requests explicitly return unsupported; there is no radio or security-lock provider.

SDK EGL lacks `EGL_KHR_lock_surface2`, required by the original caller banner. The explicit mode therefore loads a scoped adapter in those two original processes: original call-ui QPainter renders into its original X pixmap, and sysuid reads that same content through original Qt image/pixmap constructors. It pins Qt, X11 and application versions and rejects unexpected formats, processes and fences. It neither advertises a missing EGL extension nor redraws the call UI.

The combined diagnostic separates lock state, call state, button pixels and the strict graphics gate, retaining successive animation frames for review. It does not measure animation FPS or replace visible Cocoa input, acoustic or physical-phone acceptance.

See the [locked-call validation record](call-lockscreen-validation.json) for the current combined and ordinary-call regressions. Functional checks passed; the GPU warning and a thin banner-edge seam in an inspected frame remain unresolved. Full graphics acceptance has not passed.
