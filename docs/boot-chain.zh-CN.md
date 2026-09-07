# 启动链输入与 GP 引导服务

[English](boot-chain.md) · [设备服务](device-services.zh-CN.md) · [内核](kernel.zh-CN.md)

完整安全启动仍为 **BLOCKED**。本次补齐原版启动/基带输入准备，并恢复缺失的 GP `CONTROL_STATUS` 映射；现已提供显式启用的 GP 缓存服务入口，使原版加载器首次 SMC 可以返回；仍不提供 HS/BB5 安全服务、存储配置或服务凭据。

## 准备原版载荷

使用[原始媒体清单](guest-media.json)中精确匹配的 PR1.3 固件。命令只读原文件，在创建输出前验证完整大小与 SHA-256，检查全部 FIASCO 记录边界和头部校验和，并在写入完成清单前再次校验原始媒体：

```sh
python3 -B scripts/harmattan-qemu/prepare-boot-inputs.py \
  --firmware "$HARMATTAN_ORIGINAL_FIRMWARE" \
  --output "$PWD/extracted/private-boot-inputs"
```

目标目录必须尚不存在。输出包含 109 个原版非 rootfs 载荷（49,755,648 字节）及 `boot-inputs.json`。第 110 条记录描述由 `prepare-guest.py` 处理的 rootfs，不重复提取。文件以前置记录序号命名，保留所有同名类型和目标元数据；尤其不能将每种 CMT 组件的五个变体或一条记录中的多个设备字段合并为单一文件名或目标。报告保留硬件版本字符串及前导零，不选择硬件变体或 KCI。

载荷包括各 22 个 `cert-sw`、`2nd`、`xloader`、`secondary`，四个 `1st`，各五个 `cmt-2nd`、`cmt-algo`、`cmt-mcusw`，以及一个原版内核和一个 `ape-algo`。载荷与详细清单均留在私有目录。容器摘要和校验和只能证明提取完整性，不等于 Nokia 验签、设备身份或完整信任链；分发包中的软件证书不等于已配置的设备证书。

独立有界解析器的字段含义与 pancake、Pali Rohár 编写的 [0xFFFF 上游 FIASCO 读取器](https://github.com/pali/0xFFFF/blob/master/src/fiasco.c)交叉核对。它不是刷机工具，不执行 SDK 安装器，也不挂载或修改客体磁盘。

## 恢复实际 GP 分支

Nokia 原 OMAP3 模型将 SCM `general[0x20]`，即物理地址 `0x480022f0`，初始化为 `0x30f`：GP 设备类型及其 SDK 启动引脚配置。此前移植版没有映射该地址。新的 `--cocoa-interaction` 构建提供四字节寄存器及小端字节访问；写入会报告不支持的客体访问。这一小范围映射不提供其余 SCM、熔丝或安全硬件。维护补丁为 `qemu-9.1.3-n00-control-status.patch`，在 SSI 补丁之后应用。

现有 [SSI 诊断](device-services.zh-CN.md#ssi-控制器实现)在三种 SSI 模式下检查该寄存器及每个字节。新构建还使 PR1.3 `/proc/cpuinfo` 从 `ES1.0-test` 变为 `ES1.0-gp`，原版 SSI 绑定及 validator netlink 继续正常。这是恢复原有 GP 模型，没有为了满足驱动检查改用 HS 身份。

## 原版加载器证据与边界

[验证记录](boot-chain-validation.json)包含未修改的 RX-71 硬件版本 `000` 首级载荷的有界无窗口实验，其 SHA-256 为 `58f28e5e7754d804f52b4c258170c9fcb6b0b8b453e1b0bd446a9ff3896d9dd7`。代码自身的重定位常量确认 SRAM 基址为 `0x40200000`。实验通过 QEMU 通用加载器装入该地址，不带磁盘、网络、虚构 ROM 参数或指令修改。它只验证一个冷启动加载器入口，不代表完整 ROM 交接或已选定零售 N9 硬件配置。

修复寄存器前，`0x4020019c` 的读取访问未映射的 `0x480022f0`，随后进入 `0x402001cc` 的非 GP SMC 路径；修复后转入 `0x402001d4` 的 GP 分支，在 `0x402001d8` 执行条件 `SMC #0`。该历史版本的两次实验均在 `0x8` 遇到未映射的监控器向量，均不算启动通过。不能用无条件成功的 SMC 返回替代缺失的监控器。

该历史版本的干净 QEMU 构建、345 项宿主测试、CONTROL_STATUS/SSI 检查和 PR1.3 前置诊断执行通过；默认 SDK 内核的无窗口 UI 回归也通过 Home、原版 Notes/键盘、计算器、动画及 GPU 检查。独立原版 BME 回归通过，报告 8/8 档及 100%，仍仅代表硬件/IPC 范围。Cocoa 窗口、实体输入和长时间会话未测。

下一层需要兼容的 ROM/监控器执行和启动交接，再完成原版 BB5 初始化与经验证的凭据加载。原版 `validator-init` 在非 HS 开发板回退和资源令牌策略加载之前调用 `bb5_open`，因此恢复 GP 引脚值本身不能解决缺失的 `dsme::DeviceStateControl`。PA/PAFMT、软件证书和启动加载器是后续工作输入，不能证明这些功能已经实现。

## 受限 GP 缓存监控器与 UART 修复

通过 `HARMATTAN_N00_GP_CACHE_MONITOR=on`，显式在复位 MVBAR 零地址映射小型只读监控器。默认关闭，其他取值会使启动失败。它只接受小端 SVC 模式执行的 ARM `SMC #0`，且服务号必须为 `r12=1`。服务号来自固定 QEMU 源码归档所含 U-Boot 的 `OMAP3_GP_ROMCODE_API_L2_INVAL` 和 `omap_smc1` 调用路径。QEMU 的 ARM 缓存维护不模拟缓存数据阵列，因此 DSB/ISB 即可完成该缓存操作，没有构造安全校验结果。

维护的汇编通过真实 ARM Monitor 异常返回，保留 r0–r14 及 SPSR。独立的 `SP_mon` 保存一个临时寄存器，不使用调用者栈。其他服务号、HS `SMC #1`、Thumb、大端及非 SVC 调用会停在 `0x80`，不返回成功。这只实现缓存服务子集，不是 Nokia ROM 镜像、通用安全监控器、PA 验签或 BB5 实现。不支持监控器递归和其他异常向量。在其余 ROM 和启动交接尚缺失时，入口必须保留为显式实验开关。

原版加载器随后暴露 QEMU 现有 UART 地址错误：扩展区域从 UART 基址加 `0x20` 开始，回调却把区域内偏移当成完整 UART 偏移解码，导致 UART3 的 `0x49020054` 软件复位及 `0x49020058` 复位状态轮询访问错误寄存器。补丁恢复地址换算，并把完整物理地址传给现有的诊断性 32 位转 8 位回退；保留宽度警告和原有寄存器、复位语义。

使用新的 `--cocoa-interaction` 构建运行无固件检查：

```sh
python3 -B scripts/harmattan-qemu/diagnose-boot-registers.py \
  --qemu "$QEMU" --output "$NEW_REGISTER_OUTPUT"
python3 -B scripts/harmattan-qemu/diagnose-gp-cache-monitor.py \
  --qemu "$QEMU" --output "$NEW_SMC_OUTPUT"
```

SMC 诊断需要 `HARMATTAN_ARMEL_CLANG`（或 `--clang`）及匹配的 `llvm-objcopy`（或 `--objcopy`），会汇编维护源码、逐字节比对已提交的 C 头文件，实际执行寄存器/状态位保留、重复调用和所有拒绝用例。寄存器诊断检查默认/off/on/非法开关、ROM 写保护与复位、UART 字节/半字访问、字访问回退、只读状态、软件复位及相邻 16550 发送区域。输出目录必须为新建私有目录。

两项修复启用后，未修改的 GP 冷加载器从 `0x402001d8` 返回 `0x402001dc`，越过 UART 复位并写出首个串口字符。随后在 `0x40200608` 读取缺失的 ROM 函数指针 `0x1432c`（表基址 `0x14000`，偏移 `0x32c`），跳向零地址。最终停在 `0x80` 时处于 **SVC** 模式，并非 Monitor 模式的 SMC 拒绝。ROM API/传输协议与交接契约仍需依据证据实现，没有添加成功占位返回。此前的 pad-control 写入仍未映射。此冷加载器实验不能证明零售操作系统启动路径，也未验证 KCI、证书、基带固件或服务就绪。[验证记录](boot-chain-validation.json)的 `gp_cache_uart_phase` 将本轮检查与历史结果分开记录。

本轮通过全新 QEMU 构建、348 项主机测试、全部 11 项 ARM SMC 用例及启动寄存器检查。最终构建的首次 UI 回归在计算器恢复阶段捕获 1 个黑色 RAM 样本，功能及宿主图形检查通过，但整体判定失败；使用相同二进制和未修改的规则独立复测后通过，黑帧样本为 0。两次结果均保留，尚不能据此证明长时间稳定或确定首次黑帧原因。本轮未重新验证完整原版服务图、Cocoa 窗口或实体输入。
