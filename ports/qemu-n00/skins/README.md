# Optional device artwork

[简体中文](README.zh-CN.md)

No PNG or PSD is distributed here. `HARMATTAN_UI_SKIN=frame` selects an original code-drawn fallback and is the prebuilt release default. The default runtime and the native geometry tests work without artwork.

The code-drawn frame uses a flat graphite body, inset black glass and simplified hardware details. Its body and active-display proportions are derived from published N9 specifications; other dimensions are explicit project choices. See [frame geometry and sources](frame-geometry.md). Its layout is independent of the optional artwork mapping. The full guest framebuffer, glass-edge gestures and lower side-key action are preserved. Rebuild the Cocoa application to see changes to this frame; existing binaries retain their previous drawing.

The optional integration was developed against Liwen Guo / Livven's Nokia N9 PSD (2011). The recorded original page is [Nokia N9 PSD](http://livven.me/psds/nokia-n9-psd/). Its recorded usage terms are separate from this repository's code licenses and do not establish an open-source artwork license. Establish permission before use or redistribution.

For users who already have permission and the source PSD, `export-n9-livven.py` is an optional local export utility requiring `psd-tools==1.19.0`, Pillow and NumPy in a separate Python environment. It exports a 1240×2320 PNG with the expected aperture. See its `--help`; do not commit generated images.

Place the permitted local output at `ports/qemu-n00/skins/n9-black-livven.png`, rebuild `--cocoa-interaction`, then explicitly set `HARMATTAN_UI_SKIN=black` for the launcher. The build retains this attribution alongside a supplied image. `HARMATTAN_UI_SKIN=off` is the default.

The view code is MIT-marked. That notice does not license the artwork, and the synthetic test fixture is not a rendering or authenticity check of the original PSD.

Fresh interaction builds also connect the lower side key to the [original lock screen](../../../docs/lockscreen.md). The artwork remains unchanged; the hit target lives in the host view and also works with the code-drawn `frame` shell.
