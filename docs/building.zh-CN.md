# 构建与运行

[English](building.md) · [输入来源](sources.zh-CN.md) · [状态](status.zh-CN.md)

## 支持的起点

完整构建和运行路径目前面向 **Apple Silicon 原生 macOS 与 APFS**。Linux 可运行可移植主机测试；Linux 客体运行属于后续移植工作。固定 QEMU 9.1.3 是因为其 OMAP 基础与当前移植匹配，不表示它是最新版本。

可以从两条独立路径参与：

1. **源码开发**：主机测试，以及使用公开源码输入构建 QEMU/DGLES。
2. **系统运行**：额外提供历史内核、适配后的 PR1.3 客体主盘，以及链接辅助程序所需的只读客体文件系统。

对于指定的原始 SDK 安装包和 PR1.3 固件，[资源获取与准备指南](guest-inputs.zh-CN.md)提供准确下载位置及本地磁盘准备脚本。源码 DVD 不是启动镜像。没有客体输入时，也可以参与主机测试与源码构建。

## 1. 主机工具

安装 Xcode Command Line Tools，并准备 Python 3.12、Ninja、pkg-config、GLib、Pixman 和原生 C 编译器。Homebrew 用户可安装缺少的工具：

```sh
brew install python@3.12 ninja pkgconf glib pixman
export PATH="$(brew --prefix python@3.12)/libexec/bin:$PATH"
```

客体辅助程序还需要支持 ARM 后端及 `ld.lld` 的 LLVM Clang，以及 e2fsprogs 的 `debugfs`。只有 Apple 系统链接器不够。一种安装方式是：

```sh
brew install llvm lld e2fsprogs
export HARMATTAN_ARMEL_CLANG="$(brew --prefix llvm)/bin/clang"
export HARMATTAN_DEBUGFS="$(brew --prefix e2fsprogs)/sbin/debugfs"
export PATH="$(brew --prefix lld)/bin:$PATH"
```

上述命令说明可移植的工具选择方式；原始研究使用 DevEco Studio 附带的 LLVM。`HARMATTAN_ARMEL_CLANG` 也可指向该编译器。更换编译器后，应通过客体辅助程序构建与运行检查，再认定输出已验证。可用 `HARMATTAN_PYTHON`、`HARMATTAN_NINJA`、`HARMATTAN_BUILD_JOBS` 选择 Python、Ninja 和并行度。

```sh
python3 scripts/check-environment.py
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py'
```

## 2. 公开源码输入

将下列文件放入已忽略的 `downloads/tools/`，或使用对应环境变量：

| 输入 | 位置 | 覆盖变量 |
| --- | --- | --- |
| QEMU 9.1.3 发行归档 | `downloads/tools/qemu-9.1.3.tar.xz` | `HARMATTAN_QEMU_TARBALL` |
| PR1.3 DGLES 源码包 | `downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz` | `HARMATTAN_GLES_TARBALL` |

QEMU 来自[官方发行归档](https://download.qemu.org/qemu-9.1.3.tar.xz)。DGLES 包位于 Harmattan PR1.3 源码 DVD 的 `sources/` 目录。[来源说明](sources.zh-CN.md)与 [inputs.json](inputs.json)记录准确摘要。两个构建脚本均在解包前拒绝不匹配归档。

## 3. 原生构建

```sh
# 可选：不接宿主 GLES 的板级/显示构建。
sh scripts/harmattan-qemu/build-arm64-port.sh --headless

# 正常交互路径：先构建宿主图形库，再构建 QEMU。
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
```

DGLES 执行需要 macOS 图形会话。仅构建通过不代表渲染通过。产物位于已忽略的 `extracted/qemu-arm64-port/`；`HARMATTAN_PORT_WORKSPACE` 可修改 QEMU 工作目录，`HARMATTAN_DGLES_WORKSPACE` 可修改 DGLES 工作目录。自定义 DGLES 路径时，构建 QEMU 前将 `HARMATTAN_DGLES_ROOT` 指向构建后的 `gles-libs-1.4.2/dgles2`。

补丁顺序见[架构说明](architecture.zh-CN.md)，由构建脚本应用。修改补丁后请使用新的工作目录，不要把固定源码归档替换成其他 QEMU 版本。

QEMU 首次配置可能按发行包 Meson wrap 文件中的上游地址获取固定版本的子项目。依赖缺席时需要网络访问。若获取中断留下不完整子项目，请在新工作目录重试；源码归档摘要通过不代表依赖 checkout 完整。

本地 `.app` 仍引用选定的 DGLES 和 Homebrew 动态库，移动依赖后需要重新构建。需要包含依赖且可移动的应用时，请使用独立的[发行打包流程和预编译说明](releases.zh-CN.md)。

## 4. 用户自行提供客体输入

正常启动入口期望以下布局：

```text
extracted/
  pr1.0-qemu-adaptation/
    zImage-2.6.32.26-qemu
    qemu-adaptation.tar.gz
    usr/lib/libEGL.so.1.3.0
    usr/lib/libGLES_CM.so.1.4.5
    usr/lib/libGLESv2.so.1.4.9
    usr/lib/xorg/modules/drivers/omapfb_drv.so
  hybrid-pr1.3-qemu/
    arm-qemu-rm680-image-pr1.3-ui.raw
    pr1.3-rootfs-qemu-rescue.ext4
```

必需及可选文件见 `inputs.json`。已有相同布局的研究工作区时，可以按明确白名单导入：

```sh
python3 scripts/import-local-inputs.py /path/to/your/research-workspace
python3 scripts/import-local-inputs.py /path/to/your/research-workspace --apply
python3 scripts/check-environment.py --guest
```

第一条只预览。第二条拒绝覆盖已有目标、验证固定输入，并通过 APFS 克隆大磁盘文件。它不会把日志、账户、任意目录或固件导入 Git。主盘属于已准备的本地状态，没有通用的发行摘要；导入器只记录其大小，不宣称验证了盘内内容。请使用可信、停止写入且无个人数据的来源副本。

手动放置时，可通过 `HARMATTAN_KERNEL`、`HARMATTAN_GUEST_IMAGE`、`HARMATTAN_PUBLIC_ROOTFS` 覆盖内核、主盘和链接用文件系统。适配层动态库仍使用上面的相对位置。

若要将[资源获取与准备指南](guest-inputs.zh-CN.md)的产物用于源码构建，选择该输出目录，并仅复制三个必需的 SDK 链接库到已忽略的布局。`cp -n` 保留已有文件；构建器会拒绝摘要不匹配的库。

```sh
HARMATTAN_PREPARED="$PWD/extracted/guest-from-original-media"
export HARMATTAN_KERNEL="$HARMATTAN_PREPARED/zImage-2.6.32.26-qemu"
export HARMATTAN_GUEST_IMAGE="$HARMATTAN_PREPARED/harmattan-pr1.3.raw"
export HARMATTAN_PUBLIC_ROOTFS="$HARMATTAN_PREPARED/pr1.3-rootfs-qemu-rescue.ext4"
mkdir -p extracted/pr1.0-qemu-adaptation/usr/lib
for library in libEGL.so.1.3.0 libGLES_CM.so.1.4.5 libGLESv2.so.1.4.9; do
  cp -n "$HARMATTAN_PREPARED/overlay/usr/lib/$library" extracted/pr1.0-qemu-adaptation/usr/lib/
done
```

构建与启动时保留这些环境变量。独立准备脚本已经在输出磁盘内应用了 UI overlay，不要再把它应用到原始镜像。

### 已准备主盘的内容

研究布局为 MBR 磁盘，PR1.3 ext4 根文件系统位于第 2 分区，home 位于第 3 分区，以 `root=0xB302` 启动。盘内必须已安装 QEMU 救援 `preinit`、PR1.0 适配层和 UI 启动脚本。raw 容量须大于 0 且不超过 32 GiB；记录中的基线为稀疏 30 GiB 磁盘。

这一阶段的源码辅助工具包括 `preinit-rescue.sh`、`scripts/build-pr13-qemu-ui-overlay.sh` 和 `apply-pr13-ui-overlay.sh`。overlay 构建需要上面列出的历史适配文件。应用脚本**只在派生的 Harmattan 客体内部运行**，会写入客体 `/usr`、`/lib` 及服务权限；不要在宿主机或真机上执行。它不会替你提取量产固件或组装磁盘分区。

## 5. 运行与诊断

```sh
# 等待 READY 再操作；默认竖屏、无机身素材。
sh scripts/harmattan-qemu/run-arm64-ui.sh

# 有界联合回归：独立启动客体并自动退出。
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-diagnostic
```

启动器按需构建辅助程序，创建独立 APFS 克隆和 qcow2 层，使用 `-snapshot`。客体写入在退出时丢弃。每次运行产物保留在唯一命名、已忽略的目录中供检查；这不代表 Notes 内容可跨启动持久保存。克隆前应关闭来源主盘的写入进程。

正常交互开启 WFI、输入驱动活动声明、原版键盘与动画及显示交接；splash 保持关闭。常用变量：

| 变量 | 值与用途 |
| --- | --- |
| `HARMATTAN_UI_INPUT_ACTIVITY` | `on` / `off`；8 秒无输入后释放活动 |
| `HARMATTAN_UI_SKIN` | `off`（源码默认）/ `frame`（代码绘制，发行版默认）/ `black`（需自行取得素材并重新构建） |
| `HARMATTAN_UI_KEYBOARD` | `on` / `off` |
| `HARMATTAN_UI_HANDOFF` | `on` / `off` |
| `HARMATTAN_UI_RUNTIME` | `responsive`（默认）/ `legacy`（诊断对照） |

部分历史诊断模式有意保留旧默认值，联合 usability 通过不代表所有旧模式均通过。`run-pr13-ui.sh` 是历史 x86/Rosetta 路线，会写入持久派生磁盘；正常原生运行请使用上述快照入口。

## 排查

- **缺少归档**：使用准确源码包并校验摘要，不要替换为相近版本。
- **缺少客体输入**：查阅清单；构建 QEMU 不会生成客体主盘。
- **APFS 克隆失败**：来源和运行目录应位于兼容的 APFS 卷。
- **客体链接失败**：选择支持 ARM 的 LLVM 与 lld，检查 `debugfs` 和固定动态库。
- **没有图形会话**：在已登录的 macOS 桌面会话运行原生图形测试。
- **移动过产物**：按目标动态库位置重新构建 `.app`。
- **启动黑屏**：等待 `READY`，查看新运行目录；报告准确命令及简短脱敏失败片段。
