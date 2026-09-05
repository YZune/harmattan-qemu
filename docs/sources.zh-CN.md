# 来源、输入与许可

[English](sources.md) · [机器可读输入清单](inputs.json)

## 源码来源

| 组件 | 来源与版本 | 许可处理 |
| --- | --- | --- |
| QEMU 基线 | [QEMU 9.1.3 发行包](https://download.qemu.org/qemu-9.1.3.tar.xz) | QEMU 的 GPLv2 与文件级声明；不内置基线归档 |
| Nokia N00 设备代码 | [Software Heritage 修订 32530f6a](https://archive.softwareheritage.org/swh:1:rev:32530f6ab08f80a53bf56843ab793eefde75a67f/) | 补丁保留原版权与 GPL 版本选择 |
| Nokia DGLES | Harmattan PR1.3 DVD，`sources/gles-libs_1.4.2-3+0m6.tar.gz` | 保留文件级声明；部分 DGLES 文件为 MIT 风格，归档内其他组件不同 |
| 项目新增实现 | 2026-09-05 从研究基线 `621c7f7` 提取 | 无更具体声明时采用 GPL-2.0-or-later |
| 宿主外壳视图 | `n00-n9-skin.h` | 明确标记 MIT 的代码；不含素材 |
| 文档与发布工具 | 本仓库 | GPL-2.0-or-later |

Nokia 快照为 [swh:1:snp:1642de2ac147a906f0ffd726121b0e15fcdef01e](https://archive.softwareheritage.org/swh:1:snp:1642de2ac147a906f0ffd726121b0e15fcdef01e/)。恢复的源码与保存的 SDK 二进制构建标识不同，本仓库不宣称二者是逐字节对应的源码及二进制发行物。

主要恢复文件的 Git/SWH blob 标识：

| 原文件 | Blob 标识 |
| --- | --- |
| `hw/n00.c` | `bd7cee59df517c424da543a5a2975532c331fa62` |
| `hw/omap3.c` | `e9149fc88f7aa7c7593dd93a086e02f6f0bee3d9` |
| `hw/omap3_mmc.c` | `4f16c008e9c061fbf5e0f59cea3e1043c4f18a44` |
| `hw/omap_sdrc.c` | `82da88c486f25a772edfbfe0b3a2cc20ca75dc57` |
| `hw/omap_i2c.c` | `f128530ec0b34ed5c05fa126a124b7ed14d81487` |
| `hw/twl4030.c` | `a86855e3463dc64a86547102675e143391c696dc` |
| `hw/omap_dss.c` | `c1228df70d053bcd0711f7b5fc81b93777867ac5` |
| `hw/omap_dss_drawfn.h` | `37ba1369505293d83ffa0da4c32387a4be983a82` |

Git blob 标识包含对象封装，不是普通文件的 SHA-1。移植还参考同一修订中的 `omap_dma.c` 和 Nokia GLES 协议定义文件。

## 固定源码归档 SHA-256

```text
480a77a0ed13a9b39415f639aa020b4eb0d7cc5a52569510dfd830b3af1bac89  qemu-9.1.3.tar.xz
2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711  gles-libs_1.4.2-3+0m6.tar.gz
```

Harmattan 源码 DVD 是源码包集合，本身不提供完整固件构建或专有运行材料。

## 外部客体输入身份

历史运行时来自 Nokia Qt SDK 1.1.2 离线安装包，现由 [Internet Archive 条目](https://archive.org/details/nokia-qt-sdk-1.1.2)保存。其身份为 `DFL61_1.2011.22-5.S`，属于早期 PR1.0 时期，并非 PR1.2。原始研究记录了：

| 材料 | SHA-1 标识 |
| --- | --- |
| 运行时归档 `DFL61_1.2011.22-5.S.tar.gz` | `71c0aa74288fe717595cbf23998f1cf9a39bbaad` |
| 原始 SDK 主盘 QCOW2 | `6afbfbc08702d4c13b4a9cc382920caeca296aa3` |
| 原始 SDK NAND QCOW2 | `2c6757a4d3eba1eb73db5b67eb7b680c05a72ba9` |
| 提取的 PR1.3 量产 rootfs `40.2012.21-3` | `c8956957f458836353f6065ca09ad629f182699d` |

这些 SHA-1 用于标识保存的历史材料，不是现代真实性保证。新输入清单还固定了实际内核和适配文件的 SHA-256；本地准备的主盘不设置通用摘要。本仓库不提供专有客体输入的下载脚本，档案可下载也不表示允许再分发。

## 不包含的内容

不包含 SDK 安装器、固件容器、内核二进制、QCOW/raw/ext4 镜像、专有包、Nokia Pure 字体、量产主题资源、Livven PNG/PSD。新仓库历史只包含选定源码，不导入研究仓库中的下载物、日志、私人路径或客体状态。

可选外壳集成引用的 Nokia N9 PSD 由 Livven / Liwen Guo 创作。研究记录描述了个人使用及商业捐赠建议，并未确认其采用开源素材许可。用户应自行确认使用及再分发权限。正常构建和几何测试无需该素材，参见[可选外壳说明](../ports/qemu-n00/skins/README.zh-CN.md)。

## 许可适用方式

[QEMU 官方许可说明](https://www.qemu.org/docs/master/about/license.html)明确 GPLv2 及文件级条款。这里的 Nokia 原文件同时存在“GPL 第 2 或第 3 版”与“GPL 第 2 或后续版本”等声明，应保留区别。明确标记 MIT 的新增实现仍采用 MIT。不要将组合后的 QEMU 代码整体改为宽松许可，也不要将整个 DGLES 归档视作 MIT。

源码发布附根目录 GPLv2 正文、[NOTICE](../NOTICE) 及 [MIT 正文](../LICENSES/MIT.txt)。分发构建后的 QEMU 时，应按对应条款提供声明及相应源码，包括选定基线和修改。本次仅源码发布不授予外部客体软件或素材的权利。
