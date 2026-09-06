# 三方 ARMEL 应用

[English](applications.md) · [用户档案](storage.zh-CN.md) · [联网](networking.zh-CN.md)

源码启动器可将明确提供的 Harmattan `.deb` 安装到私有用户档案。先关闭使用该档案的客体，按依赖包在前、应用在后的顺序传入文件；安装器不自动下载包，也不解析在线软件源。

```sh
# 在宿主检查身份、依赖及安装脚本。
python3 scripts/harmattan-qemu/armel-packages.py downloads/applications/example_armel.deb

# 在客体内安装，保留其真实包数据库。
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" \
  sh scripts/harmattan-qemu/run-arm64-ui.sh --install-packages \
  downloads/applications/dependency_armel.deb downloads/applications/example_armel.deb

# 安装完成后打开相同档案。
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" \
  HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh
```

上述文件名是占位示例，需换成已获取、审查的包。ARM32 客体应选择 **armel** 或架构无关的 **all**；ARM64 指 Mac 上的模拟器程序，不是客体包 ABI。现代 Sailfish RPM、Android APK 和任意 Debian ARM 包不能直接替代 Harmattan 包。

安装器接受 1–24 个文件，每个最多 64 MiB、总计最多 96 MiB，使用历史 gzip Debian 包格式。它在 macOS 上只读元数据，不提取包内文件、不执行安装脚本。原始字节通过随机私有地址的回环 HTTP 服务，经 QEMU SDK 以太网传入客体；宿主记录 SHA-256，客体用 SHA-1 核对传输内容。摘要证明内容一致，不代表发布者可信。可选历史 `_x509sig` 成员原样保留，但**不验证签名**。

救援/适配客体内使用 `/usr/bin/dpkg.real` 安装，因为零售 Aegis 包装器依赖完整产品安全服务。依赖检查和安装脚本错误仍会使安装失败，不强制忽略依赖，也不对整个系统执行 `dpkg --configure -a`。安装前后会验证 SDK EGL/GLES 库摘要，并恢复被标准 `ldconfig` 触发器切回零售 SGX 驱动的已知符号链接；未知库或链接会报错。每个请求包的准确版本必须达到 `install ok installed`，随后客体 sync、QEMU 干净退出，才报告成功。失败可能在档案内留下 dpkg 的部分安装状态；日志和档案检查点会保留。评估陌生包时可选择另一个档案。

## 首批应用

首批覆盖本地笔记、文件管理和阅读。来源页面分别为 [Khertan 的 ownNotes](https://openrepos.net/content/khertan/ownnotes)、[CepiPerez 的 Filebox](https://openrepos.net/content/cepiperez/filebox) 和 [Harmattan FBReader 备份](https://openrepos.net/content/hooddy/fbreader-harmattan)。FBReader 页面属于归档上传，上传者不等于原开发者。

| 应用 | 包 | 依赖说明 |
| --- | --- | --- |
| ownNotes | `ownnotes 1.2.3 armel` | 需要匹配的 Harmattan SDK Python 2.6 组件，包括 `libpython2.6` |
| Filebox | `filebox 0.1.0 armel` | 使用客体现有 MeeGo Touch/Qt 库 |
| FBReader | `fbreader 0.99.5 armel` | 使用客体现有 Qt、curl、SQLite 和资源库 |

ownNotes 的已验证依赖顺序为 `libncurses5`、`readline-common`、`libreadline5`、`python2.6-minimal`、`python2.6`、`libpython2.6`，最后 `ownnotes`。准确版本与摘要见[应用验证记录](applications-validation.json)。这些历史包仍是用户提供的外部输入，本仓库不重新分发。

包安装、应用启动、编辑内容、重开已保存内容和在线服务分别验证。兼容结论仅适用于记录中的版本和功能。云账户、现代 TLS、已经停用的 Nokia 服务、DRM、依赖硬件的程序和广泛应用兼容仍需单独推进。

当前证据确认安装成功及档案重启后的原版桌面。编辑、文件操作和 EPUB 翻页**尚未验证**：本阶段 Mac 锁屏，原生窗口检查暂不可用。
