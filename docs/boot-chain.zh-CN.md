# 启动链输入与 GP 控制寄存器

[English](boot-chain.md) · [设备服务](device-services.zh-CN.md) · [内核](kernel.zh-CN.md)

完整安全启动仍为 **BLOCKED**。本次补齐原版启动/基带输入准备，并恢复缺失的 GP `CONTROL_STATUS` 映射；尚未安装安全监控器、配置 BB5 存储或赋予服务凭据。

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

修复寄存器前，`0x4020019c` 的读取访问未映射的 `0x480022f0`，随后进入 `0x402001cc` 的非 GP SMC 路径；修复后转入 `0x402001d4` 的 GP 分支，在 `0x402001d8` 执行条件 `SMC #0`。两次实验均在 `0x8` 遇到未映射的监控器向量，均不算启动通过。不能用无条件成功的 SMC 返回替代缺失的监控器。

干净 QEMU 构建、345 项宿主测试、CONTROL_STATUS/SSI 检查和 PR1.3 前置诊断执行通过；默认 SDK 内核的无窗口 UI 回归也通过 Home、原版 Notes/键盘、计算器、动画及 GPU 检查。独立原版 BME 回归通过，报告 8/8 档及 100%，仍仅代表硬件/IPC 范围。Cocoa 窗口、实体输入和长时间会话未测。

下一层需要兼容的 ROM/监控器执行和启动交接，再完成原版 BB5 初始化与经验证的凭据加载。原版 `validator-init` 在非 HS 开发板回退和资源令牌策略加载之前调用 `bb5_open`，因此恢复 GP 引脚值本身不能解决缺失的 `dsme::DeviceStateControl`。PA/PAFMT、软件证书和启动加载器是后续工作输入，不能证明这些功能已经实现。
