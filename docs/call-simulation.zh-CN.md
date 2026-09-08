# 模拟接听来电

[English](call-simulation.md) · [构建](building.zh-CN.md) · [声音输出](audio.zh-CN.md)

此模式通过模拟来电驱动 PR1.3 原版 `call-ui`，显示原来的来电页、接听/拒接按钮和通话计时。来电者明确标为 **N9 simulation**。无需电话账户、SIM、调制解调器或麦克风。

准备好正常的[来宾输入和 ARM 辅助程序工具](building.zh-CN.md)后：

```sh
# 独立 Cocoa 会话；启动完成后自动呈现一次模拟来电。
sh scripts/harmattan-qemu/run-call-simulation.sh

# 无声体验，不需要可选的 PulseAudio 依赖。
HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-call-simulation.sh

# 有界快照诊断：QMP 按钮操作和私有铃声输出检查。
sh scripts/harmattan-qemu/run-call-simulation.sh --headless-diagnostic

# 先显示原版待机锁屏，再触发来电；从绿色提示向上滑，随后点击接听。
sh scripts/harmattan-qemu/run-call-simulation.sh --locked

# 锁屏来电组合诊断（不要求音频依赖）。
HARMATTAN_UI_AUDIO=off sh scripts/harmattan-qemu/run-call-simulation.sh --locked-headless-diagnostic
```

专用入口默认开启私有 [PulseAudio 输出](audio.zh-CN.md)，以及它需要的 SDK 以太网传输。普通模拟器启动仍默认关闭来电模拟。已有本地启动器可通过 `HARMATTAN_UI_CALL_SIMULATION=on` 复用工具选择；此模式拒绝持久化用户配置。实验需要源码辅助程序构建器，之前下载的预构建预览版不包含它。

等待 `READY` 后操作。点击绿色按钮接听，进入原版通话页面；点击红色按钮拒接。铃声静音按钮可停止铃声并保留待接状态。通话中点击红色按钮挂断。通过通常的边缘手势回到 Home，再打开独立的 **Simulate call / 模拟来电** 图标即可再次触发。待接或通话过程中重复请求会被拒绝。关闭模拟器结束这次临时会话。

当前为可运行实验版：状态与音频检查通过，但重复来电诊断仍触发底层 GPU 纹理警告，完整图形验收未通过。诊断保留非零退出，不把警告当作通过。

## 实现与边界

小型 ARM 辅助程序实现该界面使用的原版 Telepathy `StreamedMedia`、`Group`、`Hold`、Account 和 Connection 接口子集。原版 Ring 的账户名和对象路径仅存在于独立 D-Bus 实例中；普通模式仅允许来宾用户连接。原系统总线与 NoNetwork 状态保持不变。辅助程序不启动 Ring、CSD、Mission Control、SIP 注册或媒体引擎。

私有总线还运行校验过身份的原版 GConf 守护进程，使用复制的配置目录。即使进程已持有服务名，旧客户端的 `StartServiceByName` 仍需要服务声明。此配置保持原版 Blanco 主题选择；缺少配置服务会回退到 `base`，显示红色缺失图片标记。通话程序使用原版支持的 `-software -local-theme -graphicssystem raster` 参数选择软件视口。默认系统配置以及应用、主题二进制均保持不变。该进程由启动器显式启动、检查身份，并随会话停止。

效果层接收原版通话 UI 发出的 NGF 铃声请求，通过来宾 GStreamer 和私有输出服务播放用户输入中的原版 `Nokia tune.mp3`，循环至静音、接听或通话结束。这是所需的模拟反馈，并未恢复完整 NGF 策略或物理声音路由。通话语音、麦克风静音、扬声器路由、DTMF、呼叫等待、联系人匹配、未接来电历史均不在验收范围内。计时器表示模拟通话状态。

诊断检查原版 UI、辅助程序和配置服务的身份与进程连续性、状态转换、旧通道与非法请求拒绝、原版按钮像素、缺失资源标记，以及独立的四上下文 GLES 生命周期。既有桌面 GPU 验证器保持不变；故障、非法调用、警告、缺失上下文和错误退出顺序仍会导致失败。启用音频时从私有输出监视器记录约 32 秒声音，同时检查全段和尾部，属于软件输出证据，不等同于声学测量或物理输入验收。实际执行的检查见[验证记录](call-simulation-validation.json)。

## 锁屏来电

`--locked` 启用独立的锁屏来电适配，并在第一次来电前显示待机时钟。原版 `sysuid` 呈现来电姓名、状态和绿色 **Swipe up** 提示，保留原资源中的进入、上下呼吸与滑动动画。向上滑动展开原版接听/拒接页；上滑本身不接听。这个两步操作与 [Nokia N9 的操作说明](https://devices.vodafone.com.au/nokia/n9/basic-use/answer-a-call/) 一致。此模拟入口在通话结束后恢复来电前的待机时钟或壁纸锁屏模式。

原 `call-ui` 位于私有总线，原锁屏位于桌面总线。新增来宾 root 桥接器只转发 `call` 类型的 `insertEvent`、`removeEvent` 和原版锁屏回调，检查发送进程身份。桌面策略仅为 root 增加这两个方法的发送权限，退出时移除；原 Aegis 策略保留。私有总线中的 MCE 名称仅提供经过实际 X11 窗口验证的锁屏状态查询/信号，其他设备请求明确返回不支持，不提供无线电或安全锁能力。

SDK EGL 缺少原来电横幅使用的 `EGL_KHR_lock_surface2`。显式模式因此在这两个原进程中加载限域适配：原 `call-ui` 的 QPainter 绘制到原 X pixmap，`sysuid` 使用原 Qt 图像/像素图构造函数读取同一内容。适配校验 Qt、X11 与应用版本，拒绝非预期格式、进程和 fence；不宣告不存在的 EGL 扩展，也不重绘来电 UI。

组合诊断区分锁屏、来电状态、按钮像素和严格图形门禁，并保留连续动画帧供检查。它不测量动画帧率，不替代可见 Cocoa 操作、真实声音或物理电话验收。

本次锁屏组合与普通来电回归的结果见[锁屏来电验证记录](call-lockscreen-validation.json)。功能检查通过，GPU 警告与个别帧横幅边缘细线仍未解决；未将其计为完整图形通过。
