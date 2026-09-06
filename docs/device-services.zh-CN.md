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
| BME | I²C 识别及访问 CAL 后的启动已通。空 flash 初始化和 PMM 表警告仍存在；长时间充电、温控及持久 CAL 未验证。 |
| Aegis | 原始媒体新制备磁盘中，`validator-init` 以 `BB5 open failed -1` 退出 1，缺少 `/dev/omap_sec`。挂载 securityfs 能暴露凭据接口，不能完成硬件信任链初始化。 |
| DSME | 完整 `libstartup.so` 启动无法绑定 validator 通知 socket，进入安全 MALF；最小时钟心跳不等于完整启动。 |
| MCE / CSD | 原版 D-Bus 名称所有权要求 `mce::mce` / `csd-base::csd-base` 凭据；安全初始化失败后不能正常取得所有权。 |
| 蜂窝传输 | SDK 内核的 `omap_ssi` 探测报告 `SSI HW reset failed`；调制解调器传输、ISI 资源、SIM 与网络注册仍需实现和验证。 |

不能通过移除 validator 模块、放宽 D-Bus 策略、替换凭据检查或发布虚构信号/电量值来标记服务就绪。进程存在并不足够，必须检查原版身份、总线所有权、传输与消费端状态。

## 本次验证

2026-09-07 的[验证记录](device-services-validation.json)区分了 316 项主机测试、DGLES/QEMU 全新源码构建、默认无窗口 Home 启动和独立 BME 诊断，以上均通过。

提前启动 BME 的实验在合成器就绪检查失败，保留为 FAIL。另一独立快照先验证 Home READY，再启动原版 BME 并重启原版 sysuid，状态栏从原版极低电量图标变为 8 格图标；31×20 像素区域与原素材在黑底上的合成结果完全一致。这只是有界实验路径，尚未接入默认启动器。完整 DSME/MCE/CSD 服务检查仍为 FAIL，Cocoa 窗口、实体输入和长时间会话未测。

## 源码出处

寄存器代码恢复自 [Nokia 修订 32530f6a](https://archive.softwareheritage.org/swh:1:rev:32530f6ab08f80a53bf56843ab793eefde75a67f/)，保留 GPL 第 2 或第 3 版许可声明。[源码说明](sources.zh-CN.md)记录了源码与历史二进制并非逐字节对应版本的边界。

| 原文件 | Git/SWH blob | 文件 SHA-256 |
| --- | --- | --- |
| `hw/n00.c` | `bd7cee59df517c424da543a5a2975532c331fa62` | `95b35044e44e5b1c9a43f9f4da941a79b59e0d4e6a51161e97bd04560f9427de` |
| `hw/nseries.c` | `429bfda407fdc2c8aa0562a1cbc3ddb8a2a99e13` | `6518f2ca11fc88a9f9d1964e03656f427afc70d0d72dc4054aa3bdc4aca33130` |
| `hw/twl4030.c` | `a86855e3463dc64a86547102675e143391c696dc` | `7a8453bd0bca904891137386f184535ca6a37f0acc02e0a0146d990fb5f693bf` |

PR1.3 服务契约依据 DVD 中的 `contextkit-maemo_0.7.30+0m7`、`dsme_0.63.0+0m8`、`aegis-enabler_0.0.32+0m8` 及原版客体二进制核对。公开源码树不添加固件、CAL 数据或运行截图。
