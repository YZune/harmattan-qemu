# macOS 预编译预览版

[English](releases.md)

从 [GitHub Releases](https://github.com/YZune/harmattan-qemu/releases) 下载应用及对应源码。这个实验性的 ARM64 macOS 预览版内置 QEMU、DGLES、它们依赖的非系统动态库、私有 Python 3.12.14 控制器运行时和预编译客体辅助程序。使用应用不需要安装 Homebrew、Python、LLVM 或 debugfs。

## 仍需准备的条件

- Apple Silicon Mac，系统版本满足该发行包 `minimum_macos` 的要求；导入磁盘和临时克隆所在卷需要 APFS。具体实测系统见每个 Release 的说明，在一台 Mac 上通过不代表覆盖所有支持的系统版本。
- **已经准备好的 PR1.3 raw 磁盘**，第二分区是 Linux/ext 根文件系统，总大小不超过 32 GiB，即现有原生启动器使用的磁盘。
- `zImage-2.6.32.26-qemu`，SHA-256 为 `4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e`。

应用**本身不会**把零售固件、源码 DVD、单独 rootfs 或 QCOW2 转换成上述磁盘。获取两个必需文件请按[资源获取与准备指南](https://github.com/YZune/harmattan-qemu/blob/main/docs/guest-inputs.zh-CN.md)操作：其中提供准确下载链接、校验值，以及面向指定原始材料的独立本地准备脚本。包内不包含固件、客体内核、字体、客体链接库、SDK 安装包或 Livven 外壳素材。具体输入见[清单](https://github.com/YZune/harmattan-qemu/blob/main/docs/inputs.json)。

## 使用应用

1. 核对发行版的 `SHA256SUMS`，解压应用并移动到本机可写目录，例如 Applications。
2. 打开 **Harmattan QEMU.app**。首次启动依次选择已经准备的 `.raw` 磁盘和对应内核。导入前停止对源磁盘的写入。应用会创建私有 APFS 副本并记录磁盘校验值，不修改原文件。
3. 等待原版 Home 出现。默认设备外框由项目代码绘制，不包含外部图片或标志。现有源码构建仍可使用另行提供的外壳素材。
4. 拖动滚动，使用原版屏幕键盘，关闭 QEMU 结束会话。每次快照退出都会丢弃客体修改，包括 Notes 数据。

初始包采用 **ad-hoc 签名，尚未使用 Developer ID 签名或 Apple 公证**。下载后首次尝试打开，可能需要在 macOS“隐私与安全性”中允许该应用。请先核对来源与校验值，不要全局关闭 Gatekeeper。受管设备可能需要遵循管理员的软件分发策略。

输入与配置保存在 `~/Library/Application Support/Harmattan QEMU/`。`launcher.log` 记录最近一次图形启动，`last-run.txt` 指向本次保留的临时诊断目录。替换输入后，旧配置对应的磁盘仍保存在 `inputs/`。只删除已确认不再运行且不需要的具体配置或运行目录。原始输入应另行备份，GitHub 不会保存它们。

## 命令行入口

在应用所在目录执行：

```sh
APP='./Harmattan QEMU.app/Contents/MacOS/harmattan'
"$APP" import --disk /path/to/prepared.raw --kernel /path/to/zImage-2.6.32.26-qemu
"$APP" check
"$APP" run
"$APP" run --diagnostic
```

`import --replace` 创建新配置并保留旧配置。`--configure` 重新打开文件选择界面；`run --no-frame` 使用无外框窗口。`HARMATTAN_DATA_HOME` 可为验证指定独立状态目录。`run --diagnostic` 是有时间边界的联合无窗口客体回归，不代表鼠标或可见窗口验证。辅助程序哈希、内核标识或客体组件校验失败会停止运行，不会回退到编译。

## 源码保存与重新构建

每个二进制发行版都必须附上对应源码包及许可材料，不能只提供上游下载链接。源码包包含本项目源码、补丁与脚本，固定版本 QEMU/DGLES 归档，原先需要联网获取的 DTC 源码，Python 源码，所打包动态库的源码，安装时的 Homebrew 配方及 GLib 补丁，以及应用补丁后的 QEMU/DGLES 源码树。校验值记录在 `docs/inputs.json` 和 `docs/release-sources.json`。

源码包的 `project/` 保存仓库，旁边是 `prepared-source/`、`build-recipes/` 和 `third-party-licenses/`。仓库命令应在 `project/` 中执行。请保留独立的发行资产备份。离线校验保存的源码输入：

```sh
python3 scripts/release/fetch-sources.py --offline
```

这只校验源码缓存，不会安装宿主构建工具。完整构建仍需[构建指南](https://github.com/YZune/harmattan-qemu/blob/main/docs/building.zh-CN.md)中的原生工具链；QEMU 的 Python 构建环境还需要 Meson 1.2.3 或已安装的兼容版本。源码包 `build-recipes/` 记录实际 configure 选项和 Homebrew 库修改。各组件继续遵守自身许可，本项目不会重新许可第三方代码。

维护者应使用 `build-dgles2-host.sh` 和 `build-arm64-port.sh --cocoa-interaction` 创建新的原生 QEMU/DGLES 工作目录。使用不含个人路径的构建位置。若存在 `downloads/tools/qemu-dtc-b6910bec.tar`，构建器会自动使用；也可用 `HARMATTAN_DTC_TARBALL` 指定。从准确的上游 DTC 提交执行 `git archive --format=tar --prefix=dtc/ b6910bec11614980a21e46fbccc35934b671bd81` 可恢复这一缓存。

```sh
python3 scripts/release/fetch-sources.py
sh scripts/release/build-python.sh downloads/tools/Python-3.12.14.tar.xz /tmp/new-python-work
# 构建机需指定 HARMATTAN_ARMEL_CLANG 和 HARMATTAN_DEBUGFS。
# 编译辅助程序时需要客体链接输入，它们不会被打包。
python3 scripts/release/package-macos.py \
  --qemu-source /tmp/native-work/qemu-9.1.3-interaction \
  --dgles-source /tmp/native-work/dgles2-host/gles-libs-1.4.2 \
  --python-work /tmp/new-python-work \
  --helper-work /tmp/new-helper-work \
  --output artifacts/new-release
```

打包流程检查动态库依赖是否完整、源码校验值、辅助程序 ELF/源码哈希和签名。发布前应移动应用目录，在仅含系统工具的干净环境中执行客体回归，并观察原生外框。除了仓库发布检查，还必须检查**最终源码包及二进制包**是否意外包含本地输入。Release 附上简洁验证记录；未实际执行的另一台机器验证或公证不得记为通过。

LGPL 动态库保持为 `Contents/Frameworks` 下的独立文件，接收者可以按许可重新构建、替换，并为修改后的应用施加本地签名。对应源码包及构建、重定位脚本支持这一过程。参见[第三方声明](https://github.com/YZune/harmattan-qemu/blob/main/docs/THIRD_PARTY_NOTICES.zh-CN.md)。

运行验证完成后，使用 `python3 scripts/release/verify-release.py artifacts/new-release --archive` 生成发行资产。它先核对项目源码一致性、包内文件、动态库加载路径、签名及固定归档，再生成应用 ZIP、源码压缩包和校验清单。

便于阅读的已打补丁源码树不保留指向树外的上游符号链接，其路径和目标记录在 `build-recipes/*-external-links.json`；固定上游源码归档保持原样。
