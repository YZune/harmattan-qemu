# 声音输出

[English](audio.md) · [联网](networking.zh-CN.md) · [构建](building.zh-CN.md)

源码启动器可将客体 PulseAudio 客户端连接到 Mac 当前默认的 CoreAudio 输出，为客体原版 PulseAudio 和 GStreamer 库提供软件播放通路。声音**默认关闭**。

```sh
# 源码声音输出的可选宿主依赖。
brew install pulseaudio

# 自动开启承载音频协议的 SDK 以太网。
HARMATTAN_UI_AUDIO=pulse sh scripts/harmattan-qemu/run-arm64-ui.sh

# 独立快照：原版 libpulse PCM、GStreamer WAV 播放及静音。
sh scripts/harmattan-qemu/run-arm64-ui.sh --audio-diagnostic

# 启用声音服务时的既有 UI 回归。
HARMATTAN_UI_AUDIO=pulse sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

可用 `HARMATTAN_PULSEAUDIO` 指定已安装的 `pulseaudio`，同目录必须包含匹配的 `pactl`、`parec`。诊断还需要既有 ARM LLVM/debugfs 链接环境；小型测试程序校验固定摘要后链接客体原版库，不替换它们。已经下载的预览版不包含这项可选宿主依赖及诊断程序。

每次启动独立管理一个前台 PulseAudio 进程、随机回环 TCP 端口、私有认证 cookie 和临时运行/状态目录。仅加载当次默认输出设备，禁用录音；不注册登录服务，也不接管已有用户 PulseAudio 服务。正常退出或启动失败时只停止本次创建的进程。会话运行期间切换 Mac 默认输出设备，需要重启该会话。

控制器向客体会话传入 `PULSE_SERVER` 和私有 cookie。继承环境、使用普通 PulseAudio 客户端的应用可通过 SDK 以太网输出声音。独立服务初始软件音量为 50%，Mac 原有音量/静音控制仍可使用。诊断只采集该独立输出的 monitor，不录制麦克风或其他应用音频。

启用声音的 UI 启动还会在打开应用前启动来宾原版 OHM 资源管理器。设置中的铃声预览必须先通过 `libresourceqt` 取得音频授权，才会启动 GStreamer 播放管线。启动器检查固定版本 OHM 可执行文件、存活进程，以及两项策略服务的实际归属；保留原版规则和库，服务无法就绪时明确报错。单独的 PCM/WAV 诊断不经过这项应用资源申请。

## 覆盖范围

[铃声验证记录](ringtone-validation.json)单独覆盖原版“设置 → 声音和振动 → 铃声 → Nokia tune”：原版 MP3 预览产生约 12.9 秒非静音 CoreAudio 输出，再次点击同一铃声后音频流停止。同时通过 294 项宿主测试和启用声音的 Home、Notes、键盘、计算器及切换回归。应用验证使用无窗口 QMP 点击，没有测量 Cocoa 实体输入或声学输出。

实际结果见[声音验证记录](audio-validation.json)。分别记录原版 libpulse PCM、原版 GStreamer `filesrc → wavparse → audioconvert → audioresample → pulsesink` 和既有 UI 回归。输出 monitor 检查时长、频率、音量及双声道一致性，不能据此宣称声学质量或硬件延迟已达标。

这条路径绕过客体尚不完整的 McBSP/DAC33/ALSA 硬件通路，不模拟物理扬声器路由、通话、蓝牙、麦克风或 Nokia 完整 PulseAudio 策略模块。显式连接零售 Unix socket、依赖 Nokia 策略扩展或缺失设备服务的应用仍可能失败。Nokia Music 界面、任意编解码器、长时间播放、设备切换和端到端听感需要分别验证。

宿主模块参考 [PulseAudio CoreAudio 源码](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/modules/macosx/module-coreaudio-device.c)，可选依赖见 [Homebrew PulseAudio 配方](https://formulae.brew.sh/formula/pulseaudio)。
