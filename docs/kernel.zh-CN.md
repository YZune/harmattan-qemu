# 实验性 PR1.3 内核

[English](kernel.md) · [设备服务](device-services.zh-CN.md) · [构建指南](building.zh-CN.md)

可选的 `2.6.32.54-n00-pr13` 构建将原版 PR1.3 Aegis 实现带入模拟器。它是独立探测内核，不替换默认 SDK 内核，也不等于完整安全启动链。服务前置探测已进入用户态，并成功绑定 DSME 原版 netlink 协议 25/组 1；BB5/OMAP 安全初始化及完整蜂窝、电源服务仍未完成。

## 在 Linux 上构建

需要区分大小写的 Linux 文件系统、GNU make、patch、tar、Perl、lzop、kmod/depmod、宿主 C 编译器，以及 ARM32 GCC 4.x/binutils 工具链。已验证 GCC 4.9.4 与 binutils 2.40；GCC 4.9.4 来自验签后的 [GNU 官方归档](https://ftp.gnu.org/gnu/gcc/gcc-4.9.4/)。仅构建交叉编译器时，还必须让它找到 ARM 汇编器和链接器，不能误用构建宿主的汇编器。macOS 可以运行隔离的 Linux 构建虚拟机，但必须在其 Linux 文件系统中解包源码。

提供以下原版源码 DVD 归档，构建器会在解包前校验精确 SHA-256：

| 归档 | SHA-256 |
| --- | --- |
| `kernel_2.6.32-20121301+0m8.tar.gz` | `2ceddaf3a460c21e8ab779393de9096058bf99623e620e42c98bcaf6a65b2cd8` |
| `kernel-qemu_2.6.32.20112701+0m6.tar.gz` | `1599efe16deaaee36bdcea7fa3f95dc6ca80b324c1350d1516695f4708eb7331` |
| `gles-libs_1.4.2-3+0m6.tar.gz` | `2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711` |

将它们放入 `downloads/tools/`，或用 `HARMATTAN_KERNEL_SOURCE`、`HARMATTAN_KERNEL_QEMU_SOURCE`、`HARMATTAN_GLES_TARBALL` 指定路径。在 Linux 上的检出目录运行：

```sh
export HARMATTAN_KERNEL_CROSS_COMPILE=arm-linux-gnueabi-
export HARMATTAN_KERNEL_WORKSPACE="$PWD/extracted/pr13-kernel"
sh scripts/harmattan-qemu/build-pr13-kernel.sh
```

工作目录必须尚不存在，失败构建会保留。构建器按 Nokia 原顺序应用四个 `kernel-qemu` 补丁，再应用维护的 Perl/汇编器兼容补丁。它保留 `security/aegis` 源文件字节及必要安全配置、保留原 SMC 指令，检查内核入口地址与 validator 初始化器，并构建包括 `kfgles2` 的匹配模块；不会安装到客体或宿主系统。

现代工具兼容处理包括宿主辅助程序的 `-fcommon`、显式声明 TrustZone 汇编扩展、禁用错位的 build-id 段，以及 ARM 编译参数 `-mno-unaligned-access -fno-builtin`。后者保留旧 ARM `memset` 宏的返回值契约；允许编译器按标准库语义替换返回值会破坏控制台字体分配。SLUB 调试修补不能算修复或启动通过；即使最终出现 shell，诊断仍会拒绝内核异常和分配器损坏。

模块打包会将依赖项转换为 Harmattan 原版 module-init-tools 使用的绝对路径，并移除现代二进制索引。两个仅大小写不同的 netfilter 模块均保留。旧内核缺少 `modules.order` 和内建模块元数据产生的 depmod 警告保留在构建日志中。

## 在 macOS 上准备私有探测镜像

完整传输 `kernel-bundle.tar.gz`。不要将其中模块解包到不区分大小写的文件系统：`xt_RATEEST.ko` 和 `xt_rateest.ko` 是不同模块。下面的工具校验每个产物摘要，用数字名称暂存模块，以 APFS 克隆已停止写入的准备镜像，仅向克隆的 ext4 根分区安装匹配模块目录：

```sh
python3 -B scripts/harmattan-qemu/prepare-pr13-kernel-probe.py \
  --bundle "$HARMATTAN_KERNEL_BUNDLE" \
  --image "$HARMATTAN_GUEST_IMAGE" \
  --debugfs "$HARMATTAN_DEBUGFS" \
  --output "$PWD/extracted/pr13-kernel-probe"
```

输出目录必须是新的，其中包括 `disk.raw`、`zImage-2.6.32.54-n00-pr13`、工作用根分区切片和本地来源记录。原始磁盘及其 `/lib/modules/current` 链接会保留；这只是前置条件探测，不是通用 UI 迁移。设置 `HARMATTAN_N00_SSI=on`，使用新磁盘和内核路径运行[服务前置诊断](device-services.zh-CN.md#硬件与安全前置条件)，诊断使用 `-snapshot` 并关闭网络。不要用于运行中的用户配置或实体手机。

归档和派生磁盘是私有构建产物，不生成或发布固件、证书及设备身份。编译得到 Aegis 实现、成功绑定 netlink，不会同时提供安全监控器、经验证的 KCI 交接、PA 验签、BB5 凭据、基带或 SIM。

## 验证与剩余阻塞

[2026-09-07 验证记录](kernel-validation.json)覆盖 Linux 干净源码构建、101 个匹配模块、原版 Aegis 源文件保持不变、338 项宿主测试、无窗口前置探测和原 SDK/BME 回归。新内核成功绑定 validator netlink 及原版 SSI 驱动；选定的六个 SSI/CMT/Phonet/GLES 模块均能加载。`kfgles2` 加载成功不等于图形验收。

另一独立快照有界尝试了原版完整服务配置。DSME 加载 `libstartup.so`、进入 USER 状态、接收 validator 通知，并取得 `com.nokia.dsme` 及磁盘监控、开机计时和温控管理器的总线名称。探测使用现有 `no-ext-wd,no-omap-wd` 诊断参数，未验证看门狗行为。BME 未使用 `-n`，但 DSME 因其缺少 `dsme::DeviceStateControl` 拒绝 IPC 连接，随后 BME 退出、`bmestat` 返回 2。MCE 和 CSD 也未取得必需的总线名称；CSD 进程存活不代表服务就绪。

`validator-init` 仍退出 1，`/dev/omap_sec` 缺失，KCI 为零。快照报告原版 validator `enabled=1, enforce=0`，未修改强制校验设置，不能据此认定验签或凭据通过。安全层下一步需要兼容的安全后端和经验证的启动交接，再完成原版 BB5/Aegis 凭据初始化；调制解调器/ISI 对端同样缺失。默认启动器集成、新内核 UI/Cocoa 行为、实体输入和长时间会话未验证，完整服务仍为 BLOCKED。
