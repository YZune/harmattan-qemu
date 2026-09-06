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

## 桌面绘图

Home 现在向子进程传入 `QT_GRAPHICSSYSTEM=raster` 和 `M_FORCE_LOCAL_THEME=1`。这也覆盖使用通用 `invoker --type=e` 或 `single-instance` 的桌面入口，它们不会收到其他 invoker 类型附加的 Qt 参数。Qt raster 设置可防止普通 Qt 应用默认选择尚不完整的 GLES 路径。

原版 Qt Components 图像提供器（`qt-components` 源码中的 `src/meego/mdeclarativeimageprovider.cpp`）已支持 `M_FORCE_LOCAL_THEME`。其本地提供器读取 `/usr/share/themes/blanco/meegotouch` 内的原版 Blanco 资源。选择此路径可恢复远程 pixmap 传输失败时缺失的工具栏图标和控件。应用二进制、桌面入口、QML 和主题素材均保持原样；显式请求 OpenGL 的应用仍需要独立的 GLES 兼容工作。

## 本地功能验证

[安装记录](applications-validation.json)覆盖包配置和原版桌面。后续[日常应用记录](daily-applications-validation.json)增加了以下功能检查：

| 应用 | 结果 | 已验证行为 |
| --- | --- | --- |
| ownNotes 1.2.3 | PASS | 从 Home 启动；原版控件和 Maliit；创建、保存、重开笔记；客体重启后正文内容保持一致 |
| Filebox 0.1.0 | PASS | 从 Home 启动；浏览 Documents；通过原版剪贴板界面将文本复制到 MyDocs；客体重启后源文件与副本字节一致 |
| FBReader 0.99.5 | FAIL | 原版程序及窗口已启动，但显式 `QGLWidget` 视口仍黑屏并触发不支持的 GLES 调用；EPUB 翻页未通过验收 |

这些检查使用无窗口客体中的 QMP 指针事件、原版应用身份、界面截图和已保存文件摘要。第二次启动验证了同一档案及干净的 GPU 退出。285 项宿主测试和开启音频的 Home/Notes/Maliit/Calculator/切换动画联合回归也通过。由于 Mac 锁屏，这些三方应用功能尚未验证 Cocoa 窗口中的物理鼠标操作。使用的私有有界探索驱动并非已发布的自动应用诊断器。

ownNotes 中点击 **+** 创建笔记，输入文字，从键盘内部快速下滑收起键盘，再点击编辑器返回按钮保存。未配置的 WebDAV 工作线程会报告原应用错误，但已测试的本地笔记操作正常；本次未使用云账户。Filebox 默认通过**双击**打开目录。长按文件，选择 **Copy**，等待菜单关闭后进入目标目录，再打开 **Clipboard**、选中项目并点击复制图标。每次目录或菜单切换结束后再继续操作。
