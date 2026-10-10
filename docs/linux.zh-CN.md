# 实验性 Linux 离屏运行路径

[English](linux.md) · [构建指南](building.zh-CN.md) · [原生窗口](linux-native.zh-CN.md) · [验证记录](linux-validation.json)

本文对应 [issue #3](https://github.com/YZune/harmattan-qemu/issues/3) 的有界 Linux 宿主路径：x86_64 Linux、ARM32 TCG、DGLES 与 Mesa OSMesa 软件渲染，以及 QMP 输入和 framebuffer 采集。不需要宿主 GPU、X11、Wayland 或桌面会话，即可生成真实客体画面。显式 [Godot 原生窗口](linux-native.zh-CN.md)在离屏后端上增加局部桌面输入；安装包、触摸硬件及完整设备服务仍属独立工作。Apple Silicon Cocoa 路径保留原有默认行为。

## 设计

- 沿用 QEMU 9.1.3 的 N00 板级和客体图形协议补丁。显式 Linux 模式选择 ELF 库和 OSMesa，不构建 Cocoa。
- DGLES 使用固定版本的原始 ABI 头文件及 OSMesa 后端。表面尺寸、所有权、缩放、刷新和解绑检查保护回调使用的像素缓冲区；GLES1 与 GLES2 采用相同生命周期规则。
- QEMU 在正常虚拟机清理阶段停止图形线程，早于 Mesa 的进程退出处理，并保留幂等退出兜底。此前仅在 `atexit()` 清理会在 Mesa 已释放状态后触发可复现的 `glFinish` 崩溃。
- Linux 准备阶段使用 GNU `cp --reflink=auto --sparse=always`，临时目录与输出相邻。每次 UI 运行新建 qcow2 层并使用 `-snapshot`，准备好的 raw 盘只作只读底盘；运行前必须停止底盘的其他写入者。
- 有界启动器使用标准输入输出上的 QMP 和权限为 0600 的私有串口 FIFO，关闭客体网络，不开启控制监听端口。保留原版客体身份、ABI 摘要、就绪、像素、故障和线程退出检查。

## 1. 宿主依赖

已记录的环境为 Debian 13.6 x86_64、Python 3.12.14、GCC 14.2、Clang/LLD 19.1.7、Ninja 1.12.1、Mesa 25.0.7。其他发行版和工具版本需要独立验证。Python 至少为 3.12。在 Debian 13 开发机器上，对应软件包为：

```sh
sudo apt install build-essential git curl xz-utils file perl ninja-build pkg-config \
  python3 python3-venv python3-distlib python3-pil meson \
  libglib2.0-dev libpixman-1-dev libslirp-dev libfdt-dev libosmesa6-dev \
  clang-19 lld-19 e2fsprogs 7zip liblzo2-2
export HARMATTAN_ARMEL_CLANG=clang-19
export HARMATTAN_DEBUGFS=/usr/sbin/debugfs
```

启动器所用 Python 必须能够导入 Pillow。它只把诊断 PPM 无损导出为 PNG，并检查解码后的 RGB 字节一致。也可以通过编译器、链接器和动态库搜索路径使用私有依赖目录。记录中的运行使用单独解包的 Debian 官方软件包，未替换系统库。

## 2. 获取固定公共源码

在仓库根目录执行。源码包提供 DGLES 源码，不包含客体磁盘。

```sh
mkdir -p downloads/tools
curl --fail --location -o downloads/tools/qemu-9.1.3.tar.xz \
  https://download.qemu.org/qemu-9.1.3.tar.xz
curl --fail --location \
  -o downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz \
  https://github.com/YZune/harmattan-qemu/releases/download/v0.1.0-preview.1/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz
sha256sum --check <<'EOF'
480a77a0ed13a9b39415f639aa020b4eb0d7cc5a52569510dfd830b3af1bac89  downloads/tools/qemu-9.1.3.tar.xz
c9e3eb01f9b828169d00570dfb17b24d5375cce6bee739874149dce19ed4edcc  downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz
EOF
tar -xOf downloads/tools/Harmattan-QEMU-0.1.0-preview.1-sources.tar.gz \
  harmattan-qemu-sources/project/downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz \
  > downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz
sha256sum --check <<'EOF'
2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711  downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz
EOF
```

摘要失败时应停止。构建脚本还会独立校验两个固定归档。上述源码包成员和完整摘要已于 2026-10-08 实际解包核对。各组件保留原有许可，见[来源说明](sources.zh-CN.md)与 [NOTICE](../NOTICE)。

## 3. 无固件构建与检查

补丁变化后使用新工作目录。后续命令应保留这些变量；不同工具调用的独立 shell 不会继承上次 export。

```sh
export HARMATTAN_PORT_WORKSPACE="$PWD/extracted/qemu-linux-port"
export HARMATTAN_DGLES_WORKSPACE="$HARMATTAN_PORT_WORKSPACE/dgles2-host"
export HARMATTAN_DGLES_ROOT="$HARMATTAN_DGLES_WORKSPACE/gles-libs-1.4.2/dgles2"
export HARMATTAN_BUILD_JOBS=4
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py \
  --workspace "$HARMATTAN_DGLES_WORKSPACE"
sh scripts/harmattan-qemu/build-arm64-port.sh --linux-interaction
HARMATTAN_LINUX_BUILD="$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-linux-interaction"
python3 -B scripts/harmattan-qemu/smoke-qemu-linux-cleanup.py \
  --qemu "$HARMATTAN_LINUX_BUILD/qemu-system-arm" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --output extracted/linux-cleanup-check
```

清理检查需要 glibc，输出目录必须尚不存在。极小的合成 ARM 程序检查 prelaunch/running/paused 状态下线程先于 libc 退出处理释放，不启动操作系统或创建 Mesa 渲染上下文。DGLES smoke 独立检查真实 Mesa 上下文、像素和退出。

首次 QEMU 配置可能下载固定的 Meson 子项目，完整构建还需要上述编译器和开发库。二进制保留在所选构建目录中；这不是可搬移的发行包。

保存 DGLES smoke 成功输出的准确 renderer。历史结果为 `llvmpipe (LLVM 19.1.7, 256 bits)`。客体验证器要求显式传入并完全匹配，不能只因字符串包含 `Mesa` 就接受。

## 4. 在本地准备历史客体

按[资源获取指南](guest-inputs.zh-CN.md)下载两份准确原始材料并核对摘要。Windows 安装器只作压缩归档提取，不运行它或提取出的宿主安装程序。Git 中不包含客体材料。

至少预留 30 GiB 空间用于下载、中间文件和稀疏输出。raw 盘逻辑容量为 32 GiB，不要使用会填满稀疏空洞的复制工具。Linux 在目标文件系统建立临时目录，不把大镜像放进可能很小的 `/tmp`。选择尚不存在的输出目录：

```sh
HARMATTAN_LINUX_BUILD="$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-linux-interaction"
export LD_LIBRARY_PATH="$HARMATTAN_DGLES_ROOT/objs-x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python3 -B scripts/prepare-guest.py \
  --sdk-exe downloads/guest-media/Qt_SDK_Win_offline_v1_1_2_en.exe \
  --firmware downloads/guest-media/DFL61_HARMATTAN_40.2012.21-3_PR_LEGACY_001-OEM1-958_ARM.bin \
  --output extracted/guest-from-original-media-linux \
  --sevenzip "$(command -v 7zz)" --debugfs "$HARMATTAN_DEBUGFS" \
  --lzo-library /usr/lib/x86_64-linux-gnu/liblzo2.so.2 \
  --qemu-img "$HARMATTAN_LINUX_BUILD/qemu-img" \
  --qemu-system-arm "$HARMATTAN_LINUX_BUILD/qemu-system-arm"
```

使用发行版实际安装的 7-Zip 名称，部分环境是 `7z`。准备脚本验证原始材料和 ABI 身份，只在离线客体内适配新盘，同时要求完成标记和 QEMU 正常退出。失败时保留临时目录供诊断。不得在宿主上执行客体 overlay 应用脚本。

## 5. 运行有界 UI 诊断

使用第 3 步输出的准确 renderer。路径必须明确给出，避免默选另一份历史镜像。准备目录提供内核、raw 盘、辅助程序链接用根文件系统及原始 SDK 库，不需要再复制到旧研究布局。

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' --mode startup
```

启动检查通过后，将末尾改为 `--mode usability --timeout 900`，验证原版 Home、Notes/Maliit、Calculator 及有界切换采样。每次运行新建诊断目录，也可用 `--output` 指定新目录。`--prepare-only` 只构建固定 ABI 的 ARM 客体辅助程序，不启动 UI。

成功要求 QEMU 退出码 0、图形生命周期与线程退出完整、无未知故障或拒绝，以及全部所选客体条件通过。截图来自实际 QMP framebuffer；PNG 来源记录验证其与原始 PPM 像素相同。这是 QMP 模拟输入测试，不代表实体触摸或屏幕 FPS。Linux 为软件渲染延迟显式允许最多 30 次 System UI 就绪轮询，原始默认值与判定条件保持不变。

## 证据与剩余边界

[验证记录](linux-validation.json)区分 2026-10-08 实验与整理后的代码检查。实验在 103.314 秒内到达原版 Home，Notes 输入、删除、符号布局、保存和重开，以及 Calculator `2+3=5` 均通过；退出正常、线程全部回收、图形故障和拒绝均为零。raw 盘、内核及导出的 rootfs 摘要保持不变。先前的就绪超时和退出失败记录保留，用于定位修复。

当时完整主机测试套件因环境限制 Unix socket 与 LeakSanitizer 而失败；局部测试和真实客体成功不能将其改写为完整套件通过。Linux 跳过 AppKit 测试。整理后的 CI 与当前源码构建检查单独记录。本次 Linux 改动未重跑 macOS 运行时。

此离屏记录不代表完整量产启动、蜂窝/音频/网络/浏览器/相机服务、任意应用兼容、持久配置或长时间稳定性已完成。[原生窗口记录](linux-native-validation.json)单独说明局部桌面交互及其验证边界。
