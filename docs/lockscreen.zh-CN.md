# 原版锁屏与外壳侧键

[English](lockscreen.md) · [构建与运行](building.zh-CN.md)

全新 Cocoa 交互构建将 `black` 原图外壳和代码绘制的 `frame` 外壳右侧下方按键接到原版 Harmattan 锁屏。请等待 `READY` 后再按键。

1. 按侧键锁定屏幕，显示原版待机时钟。
2. 再按一次，显示原版壁纸、日期与解锁界面。
3. 滑过屏幕解锁，返回当前应用。单击或距离不足的滑动仍保持锁定。

上方音量键维持现状。玻璃和屏幕边缘保留原有触摸路径，机身其余区域仍可拖动窗口。锁屏键随窗口缩放和留白位置变化。

普通交互启动默认启用。设置 `HARMATTAN_UI_LOCKSCREEN=off` 可关闭；使用 `HARMATTAN_UI_SKIN=frame` 可选择无需外部图片的外壳。旧 QEMU 二进制需要重新构建，仅更新启动脚本不会增加按钮。

```sh
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
HARMATTAN_UI_SKIN=frame sh scripts/harmattan-qemu/run-arm64-ui.sh

# 独立快照；验证原版界面状态和真实来宾触摸输入，随后退出。
HARMATTAN_UI_LOCKSCREEN_TEST=on \
  sh scripts/harmattan-qemu/run-arm64-ui.sh --startup-headless-diagnostic
```

目前要求正向竖屏、原版 System UI 和按实际就绪状态启动。有界诊断拒绝使用持久档案；交互启动可显式选择[用户档案](storage.zh-CN.md)，持久档案中的锁定循环尚未单独验收。

## 实现与边界

Cocoa 按钮将完整请求写入启动器每次运行的私有请求目录。启动前和退出时禁用请求入口；尚未处理完一次请求时，多次点击合并处理。现有控制器通过其串口连接调用小型来宾辅助脚本，验证原版 `sysuid`、诺基亚锁屏插件、D-Bus 所有者和实际 X11 窗口状态，再请求 `tklock_open` 模式 6（待机时钟）或模式 5（解锁界面）。界面、资源和滑动处理仍由来宾中的原版 `sysuid` 提供。

这是救援桌面中的锁屏界面接入，未恢复 MCE、PIN／设备安全锁、闲置自动锁定、物理电源键 GPIO 事件、屏幕省电或硬件休眠恢复。待机时钟使用原版低功耗**界面模式**，QEMU 仍在运行；未启用原版完全关闭显示模式。来电与通知唤醒仍不在验收范围内。

在 SDK 的 480 × 864 画布上，壁纸锁屏底部目前仍有 10 像素白边，待机时钟则覆盖完整画布。这一渲染差异尚未修复。

实际执行的检查见[验证记录](lockscreen-validation.json)。宿主点击区域测试、无窗口来宾输入和可见 Cocoa 交互分别记录。
