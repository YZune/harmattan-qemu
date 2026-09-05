# Sources, inputs, and licensing

[简体中文](sources.zh-CN.md) · [Machine-readable input manifest](inputs.json)

## Source provenance

| Component | Origin and version | License handling |
| --- | --- | --- |
| QEMU baseline | [QEMU 9.1.3 release](https://download.qemu.org/qemu-9.1.3.tar.xz) | QEMU's GPLv2 and file-specific notices; baseline archive is not vendored |
| Nokia N00 device code | [Software Heritage revision 32530f6a](https://archive.softwareheritage.org/swh:1:rev:32530f6ab08f80a53bf56843ab793eefde75a67f/) | Preserve original copyright and GPL version choices in patches |
| Nokia DGLES | Harmattan PR1.3 DVD, `sources/gles-libs_1.4.2-3+0m6.tar.gz` | Preserve per-file notices; selected DGLES files are MIT-style, other archive components differ |
| Project additions | Extracted from research baseline `621c7f7` on 2026-09-05 | GPL-2.0-or-later unless a more specific notice applies |
| Host skin view | `n00-n9-skin.h` | Explicit MIT code notice; no artwork included |
| Documentation and publication tools | This repository | GPL-2.0-or-later |
| Runtime screenshots | QMP captures from the clean build, 2026-09-05 | Depicted original UI retains its rights holders; see [capture provenance](screenshots/README.md) |

The Nokia snapshot is [swh:1:snp:1642de2ac147a906f0ffd726121b0e15fcdef01e](https://archive.softwareheritage.org/swh:1:snp:1642de2ac147a906f0ffd726121b0e15fcdef01e/). Recovered sources and the preserved SDK binary have different build identifiers; this repository does not claim they are byte-for-byte corresponding source and binary releases.

Representative recovered Git/SWH blob identifiers:

| Original file | Blob identifier |
| --- | --- |
| `hw/n00.c` | `bd7cee59df517c424da543a5a2975532c331fa62` |
| `hw/omap3.c` | `e9149fc88f7aa7c7593dd93a086e02f6f0bee3d9` |
| `hw/omap3_mmc.c` | `4f16c008e9c061fbf5e0f59cea3e1043c4f18a44` |
| `hw/omap_sdrc.c` | `82da88c486f25a772edfbfe0b3a2cc20ca75dc57` |
| `hw/omap_i2c.c` | `f128530ec0b34ed5c05fa126a124b7ed14d81487` |
| `hw/twl4030.c` | `a86855e3463dc64a86547102675e143391c696dc` |
| `hw/omap_dss.c` | `c1228df70d053bcd0711f7b5fc81b93777867ac5` |
| `hw/omap_dss_drawfn.h` | `37ba1369505293d83ffa0da4c32387a4be983a82` |

Git blob identifiers include object framing; they are not plain-file SHA-1 checksums. The port also references `omap_dma.c` and the Nokia GLES protocol definition files in that revision.

## Pinned source archive SHA-256

```text
480a77a0ed13a9b39415f639aa020b4eb0d7cc5a52569510dfd830b3af1bac89  qemu-9.1.3.tar.xz
2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711  gles-libs_1.4.2-3+0m6.tar.gz
```

The Harmattan source DVD is a source-package collection. It does not itself provide a complete firmware build or the proprietary runtime ingredients.

## External guest input identities

The historic runtime was recovered from the Nokia Qt SDK 1.1.2 offline installer, preserved under the [Internet Archive entry](https://archive.org/details/nokia-qt-sdk-1.1.2). Its identity is `DFL61_1.2011.22-5.S`, an early PR1.0-era runtime, not PR1.2. Original research recorded:

| Item | SHA-1 identifier |
| --- | --- |
| Runtime tarball `DFL61_1.2011.22-5.S.tar.gz` | `71c0aa74288fe717595cbf23998f1cf9a39bbaad` |
| Original SDK main QCOW2 | `6afbfbc08702d4c13b4a9cc382920caeca296aa3` |
| Original SDK NAND QCOW2 | `2c6757a4d3eba1eb73db5b67eb7b680c05a72ba9` |
| Extracted PR1.3 retail rootfs `40.2012.21-3` | `c8956957f458836353f6065ca09ad629f182699d` |

These SHA-1 values identify preserved historical artifacts; they are not modern authenticity guarantees. The new input manifest additionally pins SHA-256 for the actual kernel and adaptation files. It intentionally has no universal checksum for the locally prepared main disk. No download script for proprietary guest inputs is provided, and archive availability is not a redistribution permission.

## What is deliberately absent

No SDK installer, firmware container, kernel binary, QCOW/raw/ext4 image, proprietary package, standalone Nokia Pure font or retail theme asset, or Livven PNG/PSD is included. The repository contains selected source, documentation, and three reviewed runtime screenshots. It does not import the research repository's downloads, logs, private paths, or guest state. The screenshots show the original interface; the project GPL notice does not relicense the depicted content.

Livven / Liwen Guo authored the Nokia N9 PSD referenced by the optional skin integration. The research record describes personal-use terms and a commercial donation suggestion, not an established open-source artwork license. Users must establish permission for their own use and any redistribution. The normal build and geometry test do not need that artwork. See [optional skin information](../ports/qemu-n00/skins/README.md).

## Applying licenses

The [QEMU license documentation](https://www.qemu.org/docs/master/about/license.html) describes GPLv2 with file-specific terms. Original Nokia files here include both `GPL version 2 or version 3` and `GPL version 2 or later` declarations. Preserve those distinctions. Explicit MIT additions retain MIT. Do not apply a blanket permissive license to the combined QEMU code or treat the whole DGLES archive as MIT.

The root GPLv2 text, [NOTICE](../NOTICE), and [MIT text](../LICENSES/MIT.txt) accompany this release. When distributing a built QEMU, provide its applicable notices and corresponding source under the relevant terms, including the selected baseline and modifications. This release does not grant rights over separately supplied guest software or artwork.
