# 原版设备服务：实验性硬件前置条件

[English](device-services.md) · [状态](status.zh-CN.md) · [构建](building.zh-CN.md)

完整蜂窝与电源服务图**尚未跑通**。默认启动器仍使用最小救援启动。新构建的 `--cocoa-interaction` 版本可通过 `HARMATTAN_N00_SDK_POWER=on` 显式启用恢复的 SDK 电源硬件；默认值为 `off`。已有预编译应用不包含这项修改。

## 已实现范围

- Nokia 原版 BQ24153/BQ24156 充电器模型，位于 I²C2 的 `0x6b`/`0x6a`；BQ27521 电量计位于 `0x55`；恢复 TWL GP ADC 的电池电压、容量识别和温度通道。
- 原版 N00 OneNAND 器件标识及 GPMC CS0/GPIO65 连接，使用 QEMU 未提供 flash drive 时的已擦除、易失后端。未合成 CAL 内容、证书或设备身份记录。
- DMA 地址检查识别 OneNAND 的实际映射区及数据缓冲区，支持内核重新映射 GPMC CS0；DMA 错误写入 stderr，保留 QMP 协议和错误报告。
- 可移植测试覆盖芯片标识、寄存器掩码、重复起始、字节序、复位、不支持的电量计访问和 ADC 位排列。

这些是历史 SDK 寄存器模型，含固定虚拟电气参数，不模拟随时间放电、Mac 电池、SIM 或蜂窝网络。对外电池统计由原版 BME 计算；没有替换状态栏或 ContextKit 数据提供器。

新增 flash 仅在 QEMU 运行期间存在，即使 SD 使用持久用户配置，也不会保留这块 flash。不要将其当作持久 CAL 存储或在用户配置上启用完整服务。标准启动器不会自动添加 flash 分区或启动 BME。

## 有界 BME 诊断

按构建指南准备环境并保留选定的 DGLES 工作区。使用**已停止写入的、准备好的 raw 磁盘**，不能使用运行中的用户配置或实体设备。以下命令仅为自身 QEMU 进程启用实验，使用 `-snapshot`、关闭网络，并创建新输出目录：

```sh
export HARMATTAN_DGLES_RUNTIME_DIR="$HARMATTAN_DGLES_ROOT/objs-arm64"
python3 -B scripts/harmattan-qemu/diagnose-sdk-power.py \
  --qemu "$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-arm64-interaction/qemu-system-arm" \
  --kernel "$HARMATTAN_KERNEL" \
  --image "$HARMATTAN_GUEST_IMAGE" \
  --output "$HARMATTAN_PORT_WORKSPACE/sdk-power-diagnostic"
```

将 `HARMATTAN_KERNEL` 和 `HARMATTAN_GUEST_IMAGE` 设置为[客体输入指南](guest-inputs.zh-CN.md)中的制备结果。诊断检查原版 BME 和 RX-71 硬件配置摘要、SDK `config` 分区、BME 进程与 socket 存活、`bmestat` 档位有效性、QEMU 退出及宿主诊断无异常。本地保留日志和 `result.json`，包括失败结果；不会启动桌面。

客体明确使用 BME 的 `-n` 参数，将硬件/IPC 与 DSME 隔离。即使结果为 `PASS`，`full_services` 仍为 `false`；这不表示完整电源管理、MCE 权限或蜂窝服务通过验收。

原版 `bmestat`（MD5 `4a509f812807fec894c94e4793f62374`）成功时返回 IPC 读取长度 128，并非 0：其 ARM `main` 在 `0x9024` 保存读取结果，在 `0x91bc` 返回；`0xa60c` 处请求长度为 `0x80`。诊断固定该二进制身份，严格要求成功返回 128，并先验证无 BME socket 时必须返回 ENOENT（2）；其他退出码不当作成功。

分区参数来自原版 DFL61 SDK 的 Nolo 启动记录，不是零售 N9 分区布局：

```text
mtdparts=omap2-onenand:128k(bootloader),384k@128k(config),3072k@512k(kernel),1024k@3584k(log),519680k@4608k(swap)
```

## 尚缺的服务依赖

| 层次 | 实测失败或边界 |
| --- | --- |
| BME | 独立 I²C/IPC 启动已通。接入 DSME 后，DSME 因 BME 缺少 `dsme::DeviceStateControl` 拒绝连接，BME 随后退出。空 flash/PMM 警告仍存在；长时间充电、温控及持久 CAL 未验证。 |
| Aegis | 原始媒体新制备磁盘中，`validator-init` 以 `BB5 open failed -1` 退出 1，缺少 `/dev/omap_sec`。挂载 securityfs 能暴露凭据接口，不能完成硬件信任链初始化。 |
| DSME | 默认 SDK 内核无法绑定 validator 通知 socket，进入安全 MALF。可选 [PR1.3 内核](kernel.zh-CN.md)已解决绑定问题：原版 `libstartup.so` 进入 USER 并取得总线名称，BB5/Aegis 凭据仍缺失。 |
| MCE / CSD | 原版 D-Bus 名称所有权要求 `mce::mce` / `csd-base::csd-base` 凭据；安全初始化失败后不能正常取得所有权。 |
| 蜂窝传输 | 显式启用新 SSI 模型后，原版控制器驱动能绑定，CMT/Phonet/SSI 模块能加载。`phonet0` 初始为 DOWN，管理命令启用后仍报告链路未就绪。ISI 资源、SIM 和网络注册仍未实现。关闭 SSI 时，之前的复位失败仍是预期基线。 |

不能通过移除 validator 模块、放宽 D-Bus 策略、替换凭据检查或发布虚构信号/电量值来标记服务就绪。进程存在并不足够，必须检查原版身份、总线所有权、传输与消费端状态。

## 硬件与安全前置条件

完整服务需要继续补齐硬件和可用的安全后端。尚不能认定完整复刻零售启动链是唯一路径，但直启仍必须满足原版安全 API，并完成真实凭据初始化。仅恢复 SDK 寄存器模型不够：Nokia 原版 `n00.c` 的 SSI 实现只返回版本/复位状态、忽略写入；`omap3.c` 将 `CONTROL_STATUS` 设置为 `0x30f`（GP）。它们没有实现 HS 安全监控器或调制解调器。

本次诊断确定了以下依赖及实施顺序：

1. **SSI 控制器与对端：**新模型已实现下文所述的控制器复位、待传输缓冲区、IRQ 和基本 GDD 传输，时钟时序及调制解调器/ISI 对端仍未实现。探测成功不代表传输、SIM 或网络注册可用，不能把恢复原版复位桩算作完成。
2. **安全平台与启动交接：**`arch/arm/plat-omap/sec.c` 在 `omap_sec.kci` 未设置时，会在注册设备前退出。KCI 选择 `omap3_pafmt_<kci>.bin` 和 `omap3_pa_<kci>.bin`，不能猜值。打开设备还依赖 `arch/arm/mach-omap2/hs.c` 注册的后端，后者要求 HS/EMU 类型、安全 RAM 和有效的安全 RPC；PAFMT 通过 ROM 接口验签。创建设备节点、修改 SoC 类型或随意选择已有 KCI，都不能提供这个后端。
3. **兼容内核与凭据：**默认 SDK 内核缺少后续 PR1.3 源码中的 validator 通知初始化器。可选 [PR1.3 构建](kernel.zh-CN.md)现已携带原版实现及匹配模块启动。仍需通过原接口完成 BB5、证书、资源令牌和凭据策略初始化，完整服务图才能运行。

新快照报告 `OMAP3430/3530 ES1.0-test`、全零身份寄存器及 KCI 0。原始媒体内存在多组 PA 固件，但尚未建立匹配的安全监控器执行、经过验证的 KCI 交接和已初始化设备凭据。已制备 SD 镜像及已擦除的实验 OneNAND 不等于 boot-ROM 或已配置的安全存储镜像。这些依赖仍属**未实现/未验证**，不是少开几个服务开关。

下面的可重复诊断不增加硬件模拟或安全绕过。沿用 BME 命令的前置条件及输入变量，在独立快照中尝试打开安全设备、绑定 DSME 实际使用的 netlink 协议 25/组 1，并加载当前内核对应的 SSI 模块；不启动完整服务，也不修改底盘：

```sh
python3 -B scripts/harmattan-qemu/diagnose-device-prerequisites.py \
  --qemu "$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-arm64-interaction/qemu-system-arm" \
  --kernel "$HARMATTAN_KERNEL" \
  --image "$HARMATTAN_GUEST_IMAGE" \
  --output "$HARMATTAN_PORT_WORKSPACE/device-prerequisites"
```

退出 2 表示 `BLOCKED`；退出 3 表示这些有限检查成功，但完整服务仍为 `UNVERIFIED`；诊断执行异常退出 1。本地 `result.json` 可以同时记录诊断 `status: PASS` 和服务 `service_readiness: BLOCKED`，`full_services` 始终为 false。KCI 为零时报告所选固件缺失，不代表全部 PA 文件都不存在。[前置验证记录](device-prerequisites-validation.json)分别记录实测阻塞、通过的宿主测试及 BME 回归。

## SSI 控制器实现

新构建的 `--cocoa-interaction` 版本包含 `n00-ssi.c` 及其可移植核心。设置 `HARMATTAN_N00_SSI=on` 后映射到 `0x48058000`，默认 `off`，非法值会终止启动。它与 `HARMATTAN_N00_SDK_POWER` 独立，不会自动启动客体服务。

模型提供单端口/八通道、复位/配置及唤醒寄存器、每通道每方向一个待传输字、背压、接收溢出、PIO、IRQ67/68/71 连接，以及基本的非链式 32 位 GDD 传输。DMA 只允许访问板级 SDRAM 内对齐的地址；非法地址、链式传输、半传输中断请求、多点 DMA 和非 32 位 DMA 均失败，不回报块传输成功。时钟时序、电源门控、物理信号、迁移和基带语义未实现。

无对端时，TX 缓冲区保持占用，RX 保持空；不生成信号强度、SIM 或网络注册状态。`n00-ssi.loopback` 属性仅用于显式测试。下面的无固件诊断自带四字节 ARM 输入，使用 QEMU qtest 加速器，验证关闭、无对端及回环三种情况，包括实际 INTC 连接和 32 字双向 DMA 传输：

```sh
python3 -B scripts/harmattan-qemu/diagnose-ssi.py \
  --qemu "$HARMATTAN_PORT_WORKSPACE/qemu-9.1.3-interaction/build-arm64-interaction/qemu-system-arm" \
  --output "$HARMATTAN_PORT_WORKSPACE/ssi-diagnostic"
```

沿用上文 DGLES 运行环境。验证原版驱动绑定时，设置 `HARMATTAN_N00_SSI=on` 运行前置诊断。已验证快照中，`omap_ssi` 能绑定，`cmt`、`phonet`、`ssi_protocol` 和 `cmt_speech` 均能加载，并创建 DOWN 状态的 `phonet0`。启用/关闭命令能成功执行，但日志报告 `link is not ready`，不代表已建立基带链路；安全前置条件仍为 BLOCKED。[SSI 验证记录](ssi-validation.json)分别记录控制器测试、原版模块探测、BME、无窗口 UI 检查及尚未通过的完整服务验收。

## 本次验证

可选内核的[验证记录](kernel-validation.json)新增干净内核构建、338 项宿主测试、原版模块加载，以及接收 validator 通知的 DSME 启动。完整服务仍受缺失凭据及调制解调器对端阻塞；这不替代先前 UI 结果，也不代表新内核 UI 验收通过。

2026-09-07 的[验证记录](device-services-validation.json)区分了 316 项主机测试、DGLES/QEMU 全新源码构建、默认无窗口 Home 启动和独立 BME 诊断，以上均通过。

提前启动 BME 的实验在合成器就绪检查失败，保留为 FAIL。另一独立快照先验证 Home READY，再启动原版 BME 并重启原版 sysuid，状态栏从原版极低电量图标变为 8 格图标；31×20 像素区域与原素材在黑底上的合成结果完全一致。这只是有界实验路径，尚未接入默认启动器。完整 DSME/MCE/CSD 服务检查仍为 FAIL，Cocoa 窗口、实体输入和长时间会话未测。

## 源码出处

寄存器代码恢复自 [Nokia 修订 32530f6a](https://archive.softwareheritage.org/swh:1:rev:32530f6ab08f80a53bf56843ab793eefde75a67f/)，保留 GPL 第 2 或第 3 版许可声明。[源码说明](sources.zh-CN.md)记录了源码与历史二进制并非逐字节对应版本的边界。

| 原文件 | Git/SWH blob | 文件 SHA-256 |
| --- | --- | --- |
| `hw/n00.c` | `bd7cee59df517c424da543a5a2975532c331fa62` | `95b35044e44e5b1c9a43f9f4da941a79b59e0d4e6a51161e97bd04560f9427de` |
| `hw/nseries.c` | `429bfda407fdc2c8aa0562a1cbc3ddb8a2a99e13` | `6518f2ca11fc88a9f9d1964e03656f427afc70d0d72dc4054aa3bdc4aca33130` |
| `hw/twl4030.c` | `a86855e3463dc64a86547102675e143391c696dc` | `7a8453bd0bca904891137386f184535ca6a37f0acc02e0a0146d990fb5f693bf` |
| `hw/omap3.c`（安全前置条件研究） | `e9149fc88f7aa7c7593dd93a086e02f6f0bee3d9` | `679ceb26e17a5f058efef5d082a392bb7507b929450f89ad301b02b0e6d9ca7e` |

PR1.3 服务契约依据 DVD 中的 `contextkit-maemo_0.7.30+0m7`、`dsme_0.63.0+0m8`、`aegis-enabler_0.0.32+0m8` 及原版客体二进制核对。公开源码树不添加固件、CAL 数据或运行截图。

安全/SSI 源码核对及可选内核构建使用 DVD 的 `kernel_2.6.32-20121301+0m8.tar.gz`（SHA-256 `2ceddaf3a460c21e8ab779393de9096058bf99623e620e42c98bcaf6a65b2cd8`）。这不能证明默认 `2.6.32.26` SDK 内核包含相同实现。
