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
```

专用入口默认开启私有 [PulseAudio 输出](audio.zh-CN.md)，以及它需要的 SDK 以太网传输。普通模拟器启动仍默认关闭来电模拟。已有本地启动器可通过 `HARMATTAN_UI_CALL_SIMULATION=on` 复用工具选择；此模式拒绝持久化用户配置。实验需要源码辅助程序构建器，之前下载的预构建预览版不包含它。

等待 `READY` 后操作。点击绿色按钮接听，进入原版通话页面；点击红色按钮拒接。铃声静音按钮可停止铃声并保留待接状态。通话中点击红色按钮挂断。通过通常的边缘手势回到 Home，再打开独立的 **Simulate call / 模拟来电** 图标即可再次触发。待接或通话过程中重复请求会被拒绝。关闭模拟器结束这次临时会话。

当前为可运行实验版：状态与音频检查通过，但重复来电诊断仍触发底层 GPU 纹理警告，完整图形验收未通过。诊断保留非零退出，不把警告当作通过。

## 实现与边界

小型 ARM 辅助程序实现该界面使用的原版 Telepathy `StreamedMedia`、`Group`、`Hold`、Account 和 Connection 接口子集。原版 Ring 的账户名和对象路径仅存在于独立、只允许来宾用户连接的 D-Bus 实例中。原系统总线和桌面总线保留既有策略与 NoNetwork 状态。辅助程序不启动 Ring、CSD、Mission Control、SIP 注册或媒体引擎。

私有总线还运行校验过身份的原版 GConf 守护进程，使用复制的配置目录。即使进程已持有服务名，旧客户端的 `StartServiceByName` 仍需要服务声明。此配置保持原版 Blanco 主题选择；缺少配置服务会回退到 `base`，显示红色缺失图片标记。通话程序使用原版支持的 `-software -local-theme -graphicssystem raster` 参数选择软件视口。默认系统配置以及应用、主题二进制均保持不变。该进程由启动器显式启动、检查身份，并随会话停止。

效果层接收原版通话 UI 发出的 NGF 铃声请求，通过来宾 GStreamer 和私有输出服务播放用户输入中的原版 `Nokia tune.mp3`，循环至静音、接听或通话结束。这是所需的模拟反馈，并未恢复完整 NGF 策略或物理声音路由。通话语音、麦克风静音、扬声器路由、DTMF、呼叫等待、联系人匹配、未接来电历史和锁屏唤醒均不在验收范围内。计时器表示模拟通话状态。

诊断检查原版 UI、辅助程序和配置服务的身份与进程连续性、状态转换、旧通道与非法请求拒绝、原版按钮像素、缺失资源标记，以及独立的四上下文 GLES 生命周期。既有桌面 GPU 验证器保持不变；故障、非法调用、警告、缺失上下文和错误退出顺序仍会导致失败。启用音频时从私有输出监视器记录约 32 秒声音，同时检查全段和尾部，属于软件输出证据，不等同于声学测量或物理输入验收。实际执行的检查见[验证记录](call-simulation-validation.json)。
