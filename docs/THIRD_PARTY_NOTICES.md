# Binary distribution notices

[简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

Copyright remains with each component's authors. The app carries upstream notice texts in `Contents/Resources/licenses/`; its corresponding source kit carries those notices and the sources/recipes. This table identifies the selected runtime components, not every tool or component in an upstream source archive.

| Component | Runtime scope and terms |
| --- | --- |
| QEMU 9.1.3 and N00 port | GPLv2 combined program, with retained file-specific notices; includes its DTC/libfdt and other compiled subprojects |
| DGLES 1.4.2 host libraries | Upstream X11-style permission notice plus the MIT-marked Cocoa addition; the archive's GPL kernel module is not in the host libraries |
| Project launcher/controllers/guest helpers | GPL-2.0-or-later unless a file says otherwise; the frame view is MIT-marked |
| CPython 3.12.14 | Python Software Foundation license and included third-party notices; an internal standard-library subset without pip/site-packages |
| GLib 2.88.2 | LGPL-2.1-or-later; bundled shared GLib/GObject/GIO/GModule libraries |
| gettext 1.0 | Only `libintl` is bundled, under LGPL-2.1-or-later; the GPLv3 gettext tools are not bundled |
| Pixman 0.46.4 | MIT-style file notices |
| libpng 1.6.58 | libpng-2.0 notice |
| PCRE2 10.47 | BSD-3-Clause and retained third-party notices |
| Zstandard 1.5.7 | BSD-3-Clause option and retained notices |
| macOS system frameworks/libraries | Provided by the operating system; not copied into the app |

Bundling does not restrict recipients' applicable source, modification or redistribution rights. Shared libraries stay replaceable. Relocation changes install names and applies an ad-hoc signature; the source kit preserves packaging scripts and build recipes. No developer signing key is required to rebuild and locally sign a modified copy.

Nokia, N9, Harmattan and QEMU names identify the software being studied; this is an independent preservation project. The code-drawn default frame is original project code, not the Livven image. No rights to retail firmware, Nokia Pure fonts or separately supplied artwork are granted by this distribution.
