# 启动速度与响应优化

[English](performance.md) · [构建](building.zh-CN.md) · [验证记录](performance-validation.json)

正常源码启动和联合 usability 回归现在根据合成器与 Home 的真实状态判断就绪。原先无条件等待合成器和 Home 的延时，改为检查 X11 所有权、原版窗口身份与尺寸、合成器实际初始化事件，以及连续五秒不再变化的非空 Home 画面。原版滚动条必须先完成淡出。独立的五秒 settled 阶段、时钟区域处理、输入保护、程序身份、图形错误检查和动画验证器全部保留。桌面缺失或不稳定会失败，不会被记作快速启动。

`HARMATTAN_UI_STARTUP_WAITS=ready` 选择新路径；`fixed` 保留原先合成器 8 秒、Home 25 秒的等待作为对照。历史诊断模式默认仍为 `fixed`，可显式覆盖。开机视频只覆盖启动画面，本身不会加快客体运行。

## 复现有界对比

保留构建指南中相同的原生构建、客体输入和工具配置。先关闭其他模拟器运行，取消用户档案设置，每次只运行一个客体：

```sh
unset HARMATTAN_USER_PROFILE
for waits in fixed ready fixed ready fixed ready; do
  HARMATTAN_UI_STARTUP_WAITS="$waits" HARMATTAN_UI_NETWORK=off \
    HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-arm64-ui.sh --startup-headless-diagnostic
done
```

每次运行都创建独立磁盘快照，通过正常交互启动的就绪检查后退出。比较其 `ui/ready.json` 中的 `startup_wall_seconds`；`phases` 和 `startup_observations` 记录等待细节。计时从 QEMU 进程启动开始，不含源码/辅助程序构建及磁盘准备，包含诊断观察的开销。最终串口报告记录客体内存。无窗口结果不测量 Cocoa 呈现、实体输入延迟、宿主文件缓存完全冷启动或另一台 Mac。

成对测量、准确运行时身份和回归范围见 [performance-validation.json](performance-validation.json)。启动缩短不代表动画帧率更高，也不代表每个应用内部执行都更快。

在记录中的 M5 Max 上，三组交替测试结果为：

| 等待模式 | 启动中位数 | 范围 |
| --- | --- | --- |
| `fixed` | 68.839 秒 | 68.662–69.391 秒 |
| `ready` | 51.464 秒 | 51.441–51.677 秒 |

中位数缩短 **17.375 秒（25.24%）**。另一轮开启声音的回归中，原版 Notes 打开耗时 2.493 秒，客体 RAM 文字区域的按键响应中位数为 0.220 秒。按键计时包含 120 毫秒按压和采样开销，仅是当前观察，不是输入速度提升的前后对照。

## CPU 主频和内存

当前板级模型只接受 **512 MiB**、单个 **Cortex-A8**，在 ARM64 原生宿主上通过 TCG 运行 ARM32 客体。具体约束见维护中的[板级补丁](../ports/qemu-n00/qemu-9.1.3-n00.patch)。`-m 1G` 和增加虚拟 CPU 不适用于这一模型。扩大内存需要先适配 SDRAM 地址映射、启动信息，并验证客体内核。

TCG 不按真实硬件周期模拟指令耗时。修改虚拟时钟或指令计数比例不会给客体增加宿主执行能力，却可能改变设备时序。[QEMU TCG 文档](https://www.qemu.org/docs/master/devel/tcg-icount.html)解释了这一区别。本次没有改动 CPU 时钟、客体内存、动画时长和原版 UI 资源。

观察到的 Home 基线仍有大量空闲内存，没有 swap；尚无证据表明这一负载会受益于扩容。更多应用或更大文件可能不同，需要另行测量内存压力。后续响应优化应通过现有输入/framebuffer 与 CPU 探针，定位执行、图形拷贝或服务等待成本。这些探针记录客体画面采样，不能代替实体屏幕 FPS。

已下载的预览应用不会自动获得源码更新。本项验证针对选定的原生源码运行时；新版预编译打包、原生输入延迟和长时间运行仍是独立检查。
