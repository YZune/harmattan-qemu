# Optional device artwork

[简体中文](README.zh-CN.md)

No PNG or PSD is distributed here. The default runtime and the native geometry tests work without artwork.

The optional integration was developed against Liwen Guo / Livven's Nokia N9 PSD (2011). The recorded original page is [Nokia N9 PSD](http://livven.me/psds/nokia-n9-psd/). Its recorded usage terms are separate from this repository's code licenses and do not establish an open-source artwork license. Establish permission before use or redistribution.

For users who already have permission and the source PSD, `export-n9-livven.py` is an optional local export utility requiring `psd-tools==1.19.0`, Pillow and NumPy in a separate Python environment. It exports a 1240×2320 PNG with the expected aperture. See its `--help`; do not commit generated images.

Place the permitted local output at `ports/qemu-n00/skins/n9-black-livven.png`, rebuild `--cocoa-interaction`, then explicitly set `HARMATTAN_UI_SKIN=black` for the launcher. The build retains this attribution alongside a supplied image. `HARMATTAN_UI_SKIN=off` is the default.

The view code is MIT-marked. That notice does not license the artwork, and the synthetic test fixture is not a rendering or authenticity check of the original PSD.
