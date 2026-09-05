# 架构与补丁归属

[English](architecture.md)

## 分层边界

| 层 | 归属 | 主要源码 |
| --- | --- | --- |
| 宿主模拟器 | QEMU 9.1.3 与前向移植的 Nokia N00 设备 | `ports/qemu-n00/` |
| 宿主图形 | Nokia DGLES 与 Cocoa 离屏 FBO 适配 | `ports/dgles2/` |
| 客体内核及适配层 | 自行提供的 PR1.0 模拟器内核和图形 ABI | 外部输入 |
| 客体产品软件 | 自行提供的 PR1.3 原版库及应用 | 外部输入 |
| 客体兼容 | 装入独立运行的小范围辅助代码 | `scripts/harmattan-qemu/*-guest.c` 及客体脚本 |
| 验证 | 主机单元测试、QMP 输入、客体身份和像素检查 | `scripts/harmattan-qemu/tests/` 及诊断脚本 |

`n00-port-spike` 是实验机型，直接启动 ARM32 内核，不将 Harmattan 重编译为 AArch64。显示采用 Nokia 通用 DPI 路线，未实现量产 DSI 面板传输。电源行为包含直启预设和有限 idle 兼容，不是完整掉电及恢复模型。

## QEMU 补丁顺序

下表共同前缀为 `qemu-9.1.3-n00`。构建器按模式选择相应可选阶段。

| 顺序 | 后缀 | 用途 |
| --- | --- | --- |
| 1 | `.patch` | 板级、SDRC、MMC、ARM 启动、OMAP DMA |
| 2 | `-display.patch` | I²C、TWL、DSS 与 framebuffer 解码 |
| 3 | `-gles.patch` | 客体图形协议及宿主工作线程桥接 |
| 4 | `-gles-render.patch` | 受限 GLES2 shader/texture/buffer 绘制 |
| 5 | `-gles-public.patch` | 原版公共 EGL/GLES 生命周期 |
| 6 | `-gles-shell.patch` | 原版 Qt/Home 所需调用 |
| 7 | `-input.patch` | MXT/GPIO 与单指触摸 |
| 8 | `-portrait.patch` | 显示旋转与输入变换 |
| 9 | `-idle.patch` | WFI 与有限时钟、电源兼容 |
| 10 | `-profile.patch` | 可选计时探针 |
| 11 | `-scanout-probe.patch` | 可选刷新实验 |
| 12 | `-activity-probe.patch` | 可选 Cocoa 活动实验 |
| 13 | `-interaction-activity.patch` | 输入活动申请及超时释放 |
| 14 | `-n9-skin.patch` | 可选宿主视图与边缘输入几何 |
| 15 | `-cocoa-shutdown.patch` | 异步 AppKit 退出及清理 |

正常 `--cocoa-interaction` 构建包含 idle、输入活动及宿主视图和退出代码，无需素材文件。DGLES 补丁属于另一份源码归档，不应应用到 QEMU 树中。

## 客体图形与 UI

原版客体 EGL/GLES 库调用旧内核图形接口。QEMU 桥接解码已支持的调用子集，进行受限客体内存复制，通过 DGLES 执行宿主图形工作。这不是完整 PowerVR SGX 实现，也不代表完整 EGL/GLES 一致性。

原版 Xorg、Qt、Home、合成器仍在客体中运行。小型辅助代码适配已核对的矩阵、pixmap、排序、显示交接和方向行为。依赖 ABI 的辅助代码固定客体库摘要；更换镜像需要重新核对源码和 ABI。正常路径保留原版动画变换及时序，splash 仍关闭。

## 公开源码版本的整理改动

- 默认无外壳，构建允许可选素材文件缺席。
- 内核和客体主盘可以用环境变量指定。
- 客体编译器和 debugfs 不再默认依赖某位开发者的 IDE 安装。
- 外壳几何测试使用合成透明图像，不分发原素材。
- 明确的输入导入、检查工具，以及成对的中英文入口文档。

导出本仓库不会修改原始固件或已有研究工作区。
