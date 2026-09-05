# 获取内核并准备系统镜像

[English](guest-inputs.md) · [预编译应用](releases.zh-CN.md) · [原始材料清单](guest-media.json)

应用需要两个文件：准备好的 PR1.3 `.raw` 磁盘，以及 `zImage-2.6.32.26-qemu` 内核。本项目没有托管可直接下载的客体镜像。本指南使用两份准确识别的原始归档，在本地生成这两个文件；单独下载手机固件还不能直接导入应用。

请在当前仓库代码目录执行命令；如果尚未取得代码：

```sh
git clone https://github.com/YZune/harmattan-qemu.git
cd harmattan-qemu
```

## 1. 下载原始材料

| 材料 | 准确文件 | 大小 | 用途 |
| --- | --- | ---: | --- |
| [Nokia Qt SDK 1.1.2 存档](https://archive.org/details/nokia-qt-sdk-1.1.2) | [Qt_SDK_Win_offline_v1_1_2_en.exe](https://archive.org/download/nokia-qt-sdk-1.1.2/Qt_SDK_Win_offline_v1_1_2_en.exe) | 1,907,658,896 字节 | PR1.0 模拟器内核、图形适配层和原始 SDK 磁盘布局 |
| [Nokia N9 RM696 存档](https://archive.org/details/RM696) | [DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin](https://archive.org/download/RM696/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin) | 1,248,135,798 字节 | PR1.3 全球版量产根文件系统 |

Windows 安装包在 **macOS 上仅作为归档读取**，不要运行或安装它。不需要 Windows、Wine、旧版 SDK 安装环境或手机，也不会把固件刷入设备。

2026-09-05 检查时，两个精确下载入口均返回 HTTP 200，文件长度符合记录；存档元数据也符合历史 SHA-1 身份。准备脚本还会按下方 SHA-256 验证完整文件。下载站可能变化，请独立保存原始下载物及其校验值。其他镜像站的文件只有完整摘要一致才可替代；不要改用不同地区、PR 版本、SDK 版本、EMMC 镜像、源码 ISO 或手机/openmode 内核。存档可下载不代表获得再分发许可。

在仓库根目录，将上述链接的文件下载到 `downloads/guest-media/`，或执行：

```sh
mkdir -p downloads/guest-media
curl --fail --location --continue-at - \
  --output downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  https://archive.org/download/nokia-qt-sdk-1.1.2/Qt_SDK_Win_offline_v1_1_2_en.exe
curl --fail --location --continue-at - \
  --output downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  https://archive.org/download/RM696/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin
```

预期 SHA-256（同时记录在 [guest-media.json](guest-media.json)）：

```text
ce16cbd7c99e607f51789d857fe8573852a999053a79af1fa20d645457044e30  Qt_SDK_Win_offline_v1_1_2_en.exe
9614f29594f77f50dbd34d0f921c69a4e3511fc1373dfb7467d1b0e073ea3d51  DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin
```

执行 `shasum -a 256 downloads/guest-media/*` 可打印本地摘要供比较。脚本在创建工作目录前，会拒绝大小或摘要不匹配的输入。

## 2. 一次性准备工具

当前准备流程面向 Apple Silicon macOS 26.0 或更新版本（Preview 1 应用的要求），并使用系统 APFS 卷。建议至少预留 30 GiB 可用空间，用于原始材料、中间文件和稀疏产物。磁盘逻辑容量为 32 GiB；若复制工具展开了稀疏空洞，实际占用可能大幅增加。

需要 Python 3.12 或更新版本、7-Zip（`7zz`）、`debugfs` 和 liblzo2。Homebrew 用户可以安装缺少的工具：

```sh
brew install python@3.12 sevenzip e2fsprogs lzo
```

包名及 `7zz` 命令可在 Homebrew 文档核对：[sevenzip](https://formulae.brew.sh/formula/sevenzip)、[e2fsprogs](https://formulae.brew.sh/formula/e2fsprogs)、[lzo](https://formulae.brew.sh/formula/lzo)。这些工具用于准备原始材料；已经配置好输入的预编译应用，日常启动不需要它们。

下载并解压 [macOS 预编译应用](https://github.com/YZune/harmattan-qemu/releases/tag/v0.1.0-preview.1)。包内提供配套的 `qemu-img` 和原生 `qemu-system-arm`；普通上游 QEMU 没有本项目的机型。如果 macOS 阻止下载后的可执行文件，请按[预编译说明](releases.zh-CN.md)处理签名相关提示。

## 3. 创建新的磁盘

请使用当前仓库代码：最初 Preview 1 的源码包早于这个准备脚本。下面假设应用位于 `/Applications`，请把 `HARMATTAN_APP` 改为实际位置。`--output` 应位于系统 APFS 卷，且该输出目录必须尚不存在。

```sh
HARMATTAN_APP='/Applications/Harmattan QEMU.app'
"$(brew --prefix python@3.12)/bin/python3.12" -B scripts/prepare-guest.py \
  --sdk-exe downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  --firmware downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  --output extracted/guest-from-original-media \
  --sevenzip "$(brew --prefix sevenzip)/bin/7zz" \
  --debugfs "$(brew --prefix e2fsprogs)/sbin/debugfs" \
  --lzo-library "$(brew --prefix lzo)/lib/liblzo2.dylib" \
  --qemu-img "$HARMATTAN_APP/Contents/MacOS/qemu-img" \
  --qemu-system-arm "$HARMATTAN_APP/Contents/MacOS/qemu-system-arm"
```

脚本先验证两份完整输入，只提取固定 SDK 运行时组件，校验内核和图形库，还原并校验 PR1.3 根文件系统，再组装新的稀疏磁盘。保留 SDK 出厂 data/home 分区，将根分区替换为 PR1.3。随后无窗口启动新磁盘，在这个客体内部应用仓库维护的兼容层，完成同步并将根分区重新挂为只读后，停止自己启动的 QEMU。整个过程不写现有研究镜像、不在宿主挂载客体文件系统、不需要 root 权限，也不访问设备。

内部提取偏移只适用于经过完整摘要校验的指定材料，并非通用安装包或固件解析器。中间 rootfs 在修改前还有独立摘要校验。准备成功尚不能证明 UI 兼容性，请继续执行下面的诊断。

## 4. 导入并验证

成功输出包含：

| 文件 | 用途 |
| --- | --- |
| `harmattan-pr1.3.raw` | 在应用的磁盘选择器中选择它 |
| `zImage-2.6.32.26-qemu` | 在内核选择器中选择它；SHA-256 为 `4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e` |
| `prepared-inputs.json` | 原始材料与派生产物的身份记录 |
| `pr1.3-rootfs-qemu-rescue.ext4` | 已完成适配的根文件系统，供源码构建链接辅助程序；不能作为应用的磁盘输入 |
| `prepare-serial.log` | 客体内准备过程的证据 |

也可以在终端导入并测试：

```sh
HARMATTAN_APP='/Applications/Harmattan QEMU.app'
"$HARMATTAN_APP/Contents/MacOS/harmattan" import \
  --disk extracted/guest-from-original-media/harmattan-pr1.3.raw \
  --kernel extracted/guest-from-original-media/zImage-2.6.32.26-qemu
"$HARMATTAN_APP/Contents/MacOS/harmattan" run --diagnostic
"$HARMATTAN_APP/Contents/MacOS/harmattan" run
```

如果应用已经配置过输入，`import --replace` 会创建新配置并保留旧配置。准备脚本会先结束所有客体写入，再交给应用导入。应用创建输入副本，普通运行会话中的修改在退出时丢弃。

## 失败处理与长期保存

- **输入不匹配**：使用准确文件名并核对完整 SHA-256；给其他文件改名仍然不兼容。
- **准备失败**：终端打印的 `harmattan-prepare-*` 目录保留日志和中间产物，不会宣称输出已完成。修正原因后重试；已有的完整输出绝不会被覆盖。
- **兼容层启动失败**：查看 `prepare-serial.log` 和 `*.log`、`*.commands`。不要把客体脚本应用到宿主或手机。
- **输出目录重命名失败**：输出需与 `/private/tmp` 位于同一个系统 APFS 卷；脚本拒绝跨卷复制大型镜像。
- **长期保存**：独立备份两份原始下载、仓库版本、预编译应用对应源码包及完整输入目录。Git 会忽略这些材料；删除失败现场前，确认是已停止使用的具体目录，并保留需要的证据。

项目分发准备代码和材料身份，不分发 SDK、固件、提取出的内核或准备好的客体磁盘。生成的系统仍然是 PR1.3 用户态与 PR1.0 模拟器内核的组合，运行边界见[状态说明](status.zh-CN.md)。

2026-09-05 在 macOS 26.6.2 上完成了整条路径验证：原始材料提取、客体适配、只读文件系统检查，以及已发布应用的 Home、Notes、键盘、计算器和切换动画联合无窗口诊断，246 项宿主测试通过。另一台 Mac、全新工具安装及新磁盘上的 GUI 输入尚未验证。具体见[验证记录](guest-preparation-validation.json)；不承诺跨次运行的派生文件系统时间戳逐位相同。
