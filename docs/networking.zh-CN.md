# 客体联网

[English](networking.md) · [构建](building.zh-CN.md) · [状态](status.zh-CN.md)

原生构建通过 QEMU SMC91C111 设备和 libslirp，支持 SDK 内核原有的 SMC91x 以太网驱动。客体可经宿主连接获得真实 IP 联网，不需要 TAP、管理员权限或宿主端口转发。启动器默认关闭联网，显式开启方式如下：

```sh
HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh

# 新快照：DHCP、公网 DNS/HTTP 和校验完整性的双向宿主 HTTP。
sh scripts/harmattan-qemu/run-arm64-ui.sh --network-diagnostic

# 在现有桌面和应用回归中启用网络。
HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
```

按构建指南安装 libslirp 并重新构建 QEMU。更新源码不会让已经下载的预览应用自动获得此能力。启动器会在克隆磁盘前拒绝缺少联网补丁的旧二进制。

## 数据路径

板级连接遵循原始 SDK `kernel-qemu` 的 SMC 补丁：GPMC 片选 1 和 GPIO54。内核自行配置 GPMC 映射，在偏移 `0x300` 访问 SMC 寄存器。直启会禁用未连接的 CS0 启动芯片映射，避免它与内核保留的首个 MiB 重叠。真实数据包由 QEMU 原有 SMC91C111、GPMC、GPIO 模型传递至 SLIRP。

启动时，客体原版 `udhcpc` 取得 `10.0.2.15/24`、网关 `10.0.2.2` 和 DNS `10.0.2.3`。限定用途的回调核对接口、MAC 和租约，再配置路由与解析器；改动保留在本次运行使用的私有客体磁盘内。目前客户端取得一次租约后退出，自动续租及超过初始 24 小时租约的会话尚未验证。

有界诊断启动仅监听宿主回环地址的 HTTP 服务，以摘要校验随机 64 KiB 下载和上传，在客体内解析 `example.com`，并要求从 `http://example.com/` 取得非空 HTTP 200 响应。客体命令、DHCP、DNS、公网连接、内容完整性或 QEMU 退出校验失败都会使验收失败。该诊断需要公网连接，宿主离线不能记为通过。本地记录包含串口、QEMU 错误输出及 `network-result.json`。

## 应用边界

此项恢复 SDK 以太网和 IP 访问。量产机 Wi-Fi 扫描、蜂窝、原版连接管理服务图及状态栏联网指示仍属独立工作。即使直接 socket 可用，依赖这些服务的应用仍可能显示离线。界面不伪造 Wi-Fi 或移动信号。

旧 TLS 库、过期证书、已停运接口和现代网页要求，也会独立影响旧浏览器或应用。此改动不会关闭证书校验，也不代表任意三方应用兼容。已测构建与范围见[验证记录](networking-validation.json)。
