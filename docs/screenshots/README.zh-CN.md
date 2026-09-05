# 运行截图

[English](README.md) · [项目首页](../../README.zh-CN.md)

这三张 PNG 来自 2026-09-05 的干净构建客体回归，保留采集时的原始字节，展示原版 ARM Harmattan 软件在 Apple Silicon Mac 上的 QEMU 中运行。

| 截图 | 展示内容 | 原输出文件名 |
| --- | --- | --- |
| [home.png](home.png) | 原版 Home 应用列表，包括下一行部分可见的图标 | `settled.png` |
| [calculator.png](calculator.png) | 诊断输入 `2 + 3 =` 后，Calculator 显示 `5` | `calculator-sum.png` |
| [notes-keyboard.png](notes-keyboard.png) | Notes 输入 `Qemux` 并退格后，显示 `Qemu`、原版 Maliit 键盘及候选词 | `keyboard-deleted.png` |

Notes 中的文字是测试输入，采集未使用账户数据或个人笔记。状态栏来自原版 UI，其中的电池和蜂窝指示不代表已模拟真实设备服务。

## 采集来源

- 宿主：Apple Silicon ARM64，macOS 26.6.2。
- 模拟器：包含 Cocoa-interaction 支持的 QEMU 9.1.3 干净构建；本次运行选择 `-display none`。
- QEMU SHA-256：`0454a1243cf6ca38924bf818b4761e14c8100404d753d19c9bd49201fe8c68f5`，与 [release-validation.json](../release-validation.json) 一致。
- 客体：PR1.0 时期的模拟器内核及适配层，配合准备好的 PR1.3 用户态，见[构建说明](../building.zh-CN.md)。
- 运行标识：`run.E1swqs/ui`；联合可用性诊断完成后，QEMU 退出码为 0。
- 采集方式：[diagnose-arm64-shell.py](../../scripts/harmattan-qemu/diagnose-arm64-shell.py) 的 `capture()` 暂停客体执行，通过 QMP `screendump` 导出 PNG/PPM，再恢复执行。
- 文件：每张 480 × 864 像素，逐字节复制原输出，没有裁剪、拼接、机身外壳素材、修图或生成替代界面。

这些是 QEMU 客体显示面的截图，不是 macOS 窗口截图，也不是独立的浏览器原型。它们证明这些客体状态下的画面，不测量动画 FPS、输入延迟、macOS 窗口渲染或真实鼠标交互，也不能据此认定其他应用兼容。

完成构建及输入准备后运行：

```sh
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

在新运行的 `ui/` 目录中查看上表的原文件名。时间和运行状态可能不同，不要求重新运行后截图摘要完全相同。[check-public-tree.py](../../scripts/check-public-tree.py) 固定当前已审阅图片的摘要；替换截图时需要检查新画面、更新采集来源，并明确更新摘要。

## 署名

画面中的原界面、图标、字体设计及商标属于 Nokia 和各自权利人。截图用于说明模拟器实际行为，项目 GPL 声明不会重新许可其中的界面内容，见 [NOTICE](../../NOTICE)。本图库不提供固件、字体文件或独立主题素材。
