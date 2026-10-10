# 实验性 Linux 原生窗口

[English](linux-native.md) · [Linux 构建与客体准备](linux.zh-CN.md) · [验证记录](linux-native-validation.json)

此显式启用的源码路径在 Linux x86_64 上通过 Godot 4.6.3 原生窗口显示原版 480×864 Harmattan 界面。QEMU 9.1.3 仍通过 TCG 执行 ARM32 代码，DGLES 与 Mesa OSMesa 渲染原版 Home、Calculator、Notes 和 Maliit。它扩展了[有界 Linux 移植](linux.zh-CN.md)；此前的设计、构建与局部板级/渲染结果已回应 [issue #3](https://github.com/YZune/harmattan-qemu/issues/3) 的初步调查目标。它不是 Linux 发行包，也不是完整手机模拟器。

## 设计与范围

- `ports/linux-native-ui/` 负责 Godot 窗口、按比例显示 framebuffer、鼠标/键盘事件，以及可见的连接/错误状态，不重写客体应用。
- `run-linux-ui.py --mode live` 启动现有严格客体控制器。`linux-live-bridge.py` 在当前用户拥有的私有会话目录中通过本地文件与前端交换数据。只有控制器持有标准输入输出上的 QMP；不开启 HTTP、WebSocket、VNC 或 QMP 监听服务。客体网络和音频关闭。
- 每次采集只在 PPM screendump 期间暂停 QEMU，恢复后导出 PNG，并核对 RGB 像素完全一致。目标采样频率为 18 Hz，超时后不追赶连发。前端轮询与引擎渲染上限为 30 Hz；这些目标值都不代表客体 FPS。
- 仅合并尚未发布的拖动移动；释放、按键、Back 或 Quit 前先发布保留的末次坐标，保持顺序与时间戳。控制器身份及连续序号检查阻止重放。前端心跳丢失时释放持续的触摸。
- Linux 仅在 `N00_UI_POLL_READINESS_FIRST=1` 时启用先检查 System UI/Maliit 服务就绪、再读取身份的轮询；控制器会自动导出该变量。成功报告仍包含所需摘要、归属、已映射库和 ABI 证据，保留就绪预算与故障检查。默认 macOS 报告路径不变，九个合成场景已核对输出与基线逐字节一致。

macOS Cocoa 入口及默认行为保持不变。本次 Linux 工作不构成 macOS 运行时回归通过的证据。

## 构建与启动

先完成 [Linux 依赖、源码构建、DGLES smoke 与客体准备](linux.zh-CN.md)。保留选定的构建/运行库路径和 smoke 实际输出的准确 renderer。历史值为 `llvmpipe (LLVM 19.1.7, 256 bits)`；如果本机结果不同，不要直接套用该值。另外需要能够运行 Godot GL Compatibility 渲染器的图形桌面，以及命令名为 `godot` 的[官方 Godot 4.6.3](https://github.com/godotengine/godot-builds/releases/tag/4.6.3-stable)。其他 Godot 版本和显示环境需要独立验证。

### 单命令启动并管理窗口

在仓库根目录执行，保留 Linux 构建变量：

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --mode live --frontend "$(command -v godot)" --timeout 1800
```

启动器在本次输出目录中选择新的会话路径，检查控制器创建的会话和启动状态后打开原生窗口。窗口可在 Home 就绪前显示启动状态，输入仍受原有客体检查约束。只需添加一次 `--metrics` 即可同时开启控制器和前端计时；可用 `--live-session` 指定其他新路径。桌面不可用或前端启动失败都会报错，不会自动切换显示方式。

启动器同时管理前端与控制器。单纯窗口退出不能把未完成或失败的客体运行变成成功。任一端失败时，启动器会在有界时间内清理自己启动的进程并保留诊断结果。正常 Quit 仍等待控制器原有的客体和图形退出检查。

### 手动双终端启动

两个命令均在本仓库根目录、以同一用户执行。每次选择一个新的绝对会话路径，由控制器创建；不要复用旧会话或向其他用户共享目录。可更改下面示例的目录名，但两个终端必须指向同一路径。

终端 1 保留 Linux 指南中的构建变量：

```sh
export HARMATTAN_LIVE_SESSION="$PWD/extracted/linux-native-session-01"
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --mode live --live-session "$HARMATTAN_LIVE_SESSION" --timeout 1800
```

等待控制器创建新的会话目录及其 `events/` 子目录后，再启动终端 2。任一目录缺失，前端都会拒绝启动；不要自行创建它们来绕过启动流程。

终端 2：

```sh
godot --path ports/linux-native-ui -- \
  --session "$PWD/extracted/linux-native-session-01"
```

timeout 是包含客体启动的有界控制器预算，不保证 Home 出现后还可交互 30 分钟。live 模式接受 1–1800 秒；构建/准备时间另计。可用 `--output` 指定新的诊断目录。启动器拒绝持久化档案和预编译包设置；本路径使用一次性 qcow2 层与快照。客体内保存的 Notes 会在退出后丢弃。准备好的底盘必须没有其他写入者。

如需详细本地计时，在 Python 命令中添加 `--metrics`，并在 Godot 命令的 `--` 后也添加 `--metrics`。计时为可选项，不放宽就绪或输入验证。状态、输入审计、最终结果与详细计时分别保存；会话文件可能含输入文字和客体画面，应留在 Git 之外。

受管理的前端使用 Godot Dummy 音频驱动，本路径不输出音频。详细结果位于 `launch-result.json` 的 `native_lifecycle` 字段，前端诊断位于 `frontend.log`。即使已停止所有所属进程，启动取消或强制进程清理仍属于失败/取消，不能算作正常客体退出。[启动器验证记录](linux-native-launcher-validation.json)分别记录合成生命周期、真实桌面窗口和客体执行检查。

## 输入与正常退出

等待 **Live** 状态和新鲜客体画面。启动心跳持续更新但帧序号为零，表示控制器仍在启动，不代表 Home 已就绪。

- 鼠标点击和拖动映射为原始单点触摸。从侧边空白处向内拖动可执行边缘手势。**Back** 按钮或 **Escape** 请求原版右边缘返回手势，不是向客体发送硬件 Escape 键。
- 主机输入前先打开 Notes 文档和原版英式英语 Maliit 字母键盘。支持 ASCII 字母（含 Shift 大小写）、空格、Enter、Backspace、逗号和句号；桥接必须识别到可见字母布局。数字、其他符号或布局使用屏幕键盘。不支持或未识别的输入会显示错误。这是通过坐标操作原版客体键盘，不是剪贴板粘贴、宿主输入法集成或直接编辑客体文件。
- 失去焦点、状态/画面过期、输入失败时禁用交互，并在仍可联系控制器时释放触摸。事件被确认只表示已处理，不证明对应应用操作成功。
- 使用 **Quit** 或窗口关闭控件。前端请求控制器清理，并等待确认和终态；确认成功退出后，前端以退出码 0 关闭。启动期间的取消会在下一个有界辅助程序/串口检查点生效，不会立即中断正在执行的步骤。核对启动结果为成功、QEMU 退出码 0、图形清理正常、worker 全部回收；单纯窗口关闭不足以证明客体干净退出。

## 失败与就绪

构建输入缺失/不匹配、renderer 错误、会话路径复用/不安全、画面无效、序号断档或控制器状态过期都应保留为失败，不要修改状态文件或绕过检查来强制进入 **Live**。启动超时后查看诊断 `controller.log` 及结果 JSON，补齐输入或排除就绪失败，再使用新会话。启动器限制控制器运行时间，失败时清理自己创建的进程组。手动模式下，控制器不可用或失败时，**Close** 仅以退出码 2 关闭前端，并明确标示清理尚未确认。使用 `--frontend` 时，启动器会在有界时间内清理两个所属进程组，并在终端报告失败。保留控制器输出并检查终态，不要把最后一帧或本地窗口关闭当作客体仍在运行或已经干净退出的证明。

## 已记录结果及边界

[单命令启动器验证记录](linux-native-launcher-validation.json)记录了 2026-10-10 从原始媒体重新准备输入后，对实现提交 `0dfaf046339ea2551d4025eea789822de083ff77` 的真实原生窗口复验。受管理的启动命令自动打开窗口，113.055 秒通过启动门禁，并完成 Calculator `2+3=5`、鼠标边缘拖动、Notes 输入/编辑/保存、Escape 返回及原生 Quit。控制器、QEMU 和 Godot 均自然退出且退出码为 0；图形清理通过，计数故障/拒绝为零，worker 全部回收。61 条输入审计序列中 60 条接受，紧邻 Quit 之前的 release 按既有退出优先规则取消。观察到的应用操作均已完成；确认序号不等于接受事件数。

第二个全新会话在 112.567 秒进入 Home，180 秒控制器预算到期后真实窗口自然关闭，三个退出码再次为 0，图形清理正常。这些是有界 Linux 交互/生命周期检查，不构成性能对比、持久化测试、完整系统服务验收或 macOS 运行时复验。记录另列恢复输入校验、底盘保留检查和跨平台 CI 证据；私有画面、日志及客体媒体不进入仓库。

[验证记录](linux-native-validation.json)区分历史私有实验和公开整合代码的检查。私有优化轮次通过操作系统界面自动化产生原生桌面鼠标/键盘事件，完成 Calculator `2+3=5`、实际窗口边缘拖动、Notes `Linux` → `Linu` → `Linux works`、保存、Escape 返回及原生 Quit。66 个事件全部接受；QEMU/控制器退出码 0，计数图形故障/拒绝为零，worker 全部回收。相同源码、新缓存复测通过计算器/重开/清除/重算/边缘返回/退出，80 个事件全部接受。底盘保留检查使用元数据，没有重新完整计算磁盘摘要。五个选定 Calculator 帧的静态控件区域 RGB 相同，仅是有界一致性检查。

比较窗口为 Home 空闲时首帧发布后第 5 至 35 秒，共 30 秒：

| 观测指标 | 基线 | 优化后 |
| --- | ---: | ---: |
| 前端绘制后观测到的新抓帧 | 4.891 Hz | 17.974 Hz |
| 前端 CPU，一个逻辑核 = 100% | 503.771% | 74.417% |
| 控制器 CPU | 13.531% | 39.254% |
| QEMU CPU | 1.903% | 4.954% |
| 上述三个进程之和 | 519.205% | 118.625% |
| 发布至绘制后回调，中位数 / p95 | 43 / 75 ms | 24 / 41 ms |

复测在相同空闲窗口观测到 17.898 Hz。这些是采样/传输和前端回调指标，不是客体 FPS、物理扫描输出或光子延迟。CPU 由进程累计时间与窗口边界插值计算，多线程值可超过 100%。

边缘拖动释放至控制器最终确认的尾部耗时为 1,136 → 19 ms。手势路径相同，但持续时间分别为 806 和 500 ms，不是完全相同的动作重放。计时从 Godot 输入回调开始，不是从实体输入开始；结果只说明这两次手势中观察到的队列减少，不保证硬件输入延迟。

带计时基线启动为 160.596 s，优化后为 107.062 s，相同源码新缓存复测为 105.471 s。更早源码版本曾为 161.215 和 131.403 s。首次优化启动的部分阶段与主机测试并行，复测没有。就绪过程、缓存、宿主负载会变化，前端 CPU 竞争和摘要读取顺序也同时改变。这几次运行不能隔离单项优化效果或证明固定启动加速；嵌套计时不能与其外层阶段重复相加。

历史 426 项主机测试有 9 个 LeakSanitizer/ptrace 失败、4 个 Unix socket 权限错误及 7 项跳过，不是全绿。其中 15 项桥接与 5 项轮询测试通过，Godot 解析和 227 个合成前端断言通过。随后 PR #30 完成了 31 项桥接、4 项启动生命周期、7 项轮询测试，以及 7 项 Godot 包装测试（关闭/开启计时分别为 358/357 个断言）。最终本地主机套件运行 455 项，有 9 个失败、5 个错误及 7 项跳过，原因是 LeakSanitizer/ptrace、Unix socket 限制和 Clang 缺失。跨平台 CI 已单独通过，链接见下文。这些属于源码/协议检查；PR #30 整理发布路径后没有重跑完整客体/原生流程，因为准备好的输入当时已不可用。

未声称已支持 Linux 安装包、持久化档案、完整量产启动/服务、蜂窝、浏览器/网络/音频/相机、物理 GPU 加速、任意应用/键盘布局、触摸硬件、长会话或完整 macOS 回归。此次源码新增内容不包含客体媒体、原始日志、截图或第三方二进制。

实现提交已通过 [Linux/macOS 主机与 Godot CI](https://github.com/YZune/harmattan-qemu/actions/runs/38032681606)。两组主机任务各运行 448 项测试（Linux 跳过 8 项，macOS 跳过 4 项）；独立 Godot 任务的 7 项包装测试全部通过。首次 macOS 运行暴露了一项测试假设 `/proc` 存在的问题，已改用确定性测试数据修复。这些检查不增加客体/原生桌面或 macOS 运行时复测结论。
