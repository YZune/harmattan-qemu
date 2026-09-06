# Sound output

[简体中文](audio.zh-CN.md) · [Networking](networking.md) · [Building](building.md)

Source launches can send guest PulseAudio clients to the Mac's current default CoreAudio output. This provides a working software path for the guest's original PulseAudio and GStreamer libraries. Sound remains **off by default**.

```sh
# Optional host dependency for source audio output.
brew install pulseaudio

# Automatically enables SDK Ethernet, which carries the audio protocol.
HARMATTAN_UI_AUDIO=pulse sh scripts/harmattan-qemu/run-arm64-ui.sh

# Separate snapshot: original libpulse PCM, GStreamer WAV playback and mute.
sh scripts/harmattan-qemu/run-arm64-ui.sh --audio-diagnostic

# Existing UI regression with the audio service enabled.
HARMATTAN_UI_AUDIO=pulse sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

`HARMATTAN_PULSEAUDIO` can select an installed `pulseaudio` executable; its matching `pactl` and `parec` must be beside it. The diagnostic also needs the existing ARM LLVM/debugfs linking prerequisites. A source-built helper links the original guest libraries after checking their pinned hashes. It does not replace those libraries. Previously downloaded previews do not contain this optional host dependency or diagnostic helper.

Each launch owns a separate foreground PulseAudio process, a random loopback TCP port, a private authentication cookie, and temporary runtime/state directories. It loads only the current default output device with recording disabled. It neither starts a login service nor connects to an existing user PulseAudio daemon. Normal exit and failed startup stop only the process created for that run. Changing the Mac's default output device while a session is running requires restarting that session.

The guest session receives `PULSE_SERVER` and its private cookie through the controller. Applications that inherit this environment and use the normal PulseAudio client path can send output over SDK Ethernet. The private server starts at 50% software volume; the Mac's normal volume/mute controls remain available. The diagnostic's short tones are measured through this private output's monitor, never a microphone or other application audio.

## Coverage

See the [audio validation record](audio-validation.json) for actual results. The checks distinguish original libpulse PCM, original GStreamer `filesrc → wavparse → audioconvert → audioresample → pulsesink`, and the existing UI regression. The output monitor verifies duration, frequency, level and equal stereo channels; it does not establish acoustic quality or hardware latency.

This route bypasses the guest's incomplete McBSP/DAC33/ALSA hardware path. It does not emulate physical speaker routing, telephony, Bluetooth, microphone input or Nokia's full PulseAudio policy modules. Applications that explicitly connect to the retail Unix socket, require Nokia policy extensions, or depend on missing device services may still fail. Nokia Music UI, arbitrary codecs, long playback, device switching and end-to-end audible assessment require their own validation.

The underlying host modules are documented in the [PulseAudio CoreAudio source](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/modules/macosx/module-coreaudio-device.c); the optional package is the [Homebrew PulseAudio formula](https://formulae.brew.sh/formula/pulseaudio).
