# 有界安全可行性审计

[English](security-feasibility.md) · [设备服务](device-services.zh-CN.md)

当前决定暂停 ROM/cold-loader 和调制解调器对端扩展，保留已有显式实验，优先改善原版桌面的可用性。下面的材料审计没有找到经过验证、能够在不改动零售 PR1.3 安全服务图的条件下完成初始化的 GP/SDK 后端。这是限定材料范围的否定结果，不代表历史上不存在此类实现。

## 已核对材料

| 原始输入 | 观测 | 结论 |
| --- | --- | --- |
| PR1.3 源码 DVD，`aegis-enabler 0.0.32+0m8` | `validator-init.cpp` 调用 `platsec_open`；`platsec.c` 首先调用 `bb5_open(NULL)`。非 HS 开发板处理位于后续 RDC 检查。 | 支持开发板的注释不能保证 BB5 打开成功，也不能完成凭据初始化。 |
| 同一源码 DVD 文件清单 | 有 Aegis enabler/crypto、证书管理、builder、凭据和资源令牌源码；按包名检索未找到 `libbb5`、`platsec`、`libcal`；enabler 依赖 `libbb5-dev` 与 `libcal-dev`。 | 此 DVD 未以这些包名提供缺失后端的实现和头文件。 |
| 原版 DFL61 `1.2011.22-5.S` SDK 磁盘，从新建 raw 派生文件只读提取 | 安装的 `libbb5-0`、`libbb5-secbins` 均为 `2.5.36+0m6`。包描述明确使用 `/dev/omap_sec`；库字符串及 `bb5_open` 反汇编保留设备打开路径。 | SDK 库不能作为独立于该设备的软件安全后端证据。本次没有跨版本替换库。 |
| 同一 SDK 磁盘 | 无 `aegis-enabler` 包条目；`/etc/init/aegis.conf` 挂载 securityfs 并按需运行 `libcreds-audit`，没有调用零售 `validator-init`。 | SDK 启动不等同于零售 PR1.3 信任链初始化。本次只检查镜像，没有启动原版 SDK。 |
| 原版内核源码及先前前置诊断 | `sec.c` 在注册安全设备前拒绝 KCI 为零；`hs.c` 后端要求 HS/EMU 状态及安全 RPC/PA 验签。 | 创建设备节点或改变 GP strap 均不能建立匹配后端。参见[内核证据](kernel-validation.json)。 |

提取的 SDK `libbb5.so.0.0.0` SHA-256 为 `034a7dc91736bbc91cd170c8fb811e0cdfd627d17b15122924848dd760844e91`；核对的零售版本为 `965ce75b1bc2217a37cf525ecfc3f830cbd66431d7e2533b5551b914d6cda208`。私有磁盘、提取的二进制和日志均不进入 Git。本次审计没有改动固件、凭据策略或安全检查。

## 恢复推进的条件

只有取得来源可追溯、版本匹配的后端或有文档支持的交接机制，且能够通过原接口验证时，才恢复安全实现：`bb5_open` 成功、原版 validator 初始化、DSME/MCE/CSD 所需凭据以及实际 D-Bus 名称所有权。保留负向测试与失败记录。无关 SDK 库、PA 文件名、猜测的 KCI、GP cache SMC 返回或仅有守护进程运行，都不满足此门槛。

蜂窝还额外需要调制解调器/ISI 对端、SIM 状态及网络注册。取得这些前置证据前，保持原版 NoNetwork 显示，完整服务继续标记为阻塞。可选 BME 桌面模式具有独立使用价值，范围仍明确限定为 SDK 虚拟电源硬件。
