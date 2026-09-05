# QEMU 9.1.3 的 N00 前向移植

[English](README.md) · [构建](../../docs/building.zh-CN.md) · [架构与补丁顺序](../../docs/architecture.zh-CN.md)

本目录包含维护中的补丁序列及可选 Cocoa 视图代码。使用 `scripts/harmattan-qemu/build-arm64-port.sh` 应用补丁，正常交互配置为 `--cocoa-interaction`。

机型为 `n00-port-spike`：实验性的 OMAP3/N00 直启、存储、DPI 显示、受限 GLES 及 MXT 输入。兼容范围见[状态](../../docs/status.zh-CN.md)，Nokia/QEMU 来源和许可选择见[来源](../../docs/sources.zh-CN.md)。

[DGLES 补丁](../dgles2/README.zh-CN.md)应用于独立源码归档。[机身素材](skins/README.zh-CN.md)为可选、用户自行提供，本次发布不包含素材。
