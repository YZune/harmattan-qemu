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

## HTTPS 信任库

准备后的客体缺少原版 Qt/OpenSSL 浏览器使用的标准 CA 目录。UI 启动可显式采用所选宿主 Python 当前的 TLS CA 信任库：

```sh
HARMATTAN_UI_NETWORK=user HARMATTAN_UI_CA_CERTIFICATES=host \
  sh scripts/harmattan-qemu/run-arm64-ui.sh
```

控制器只导出该信任库的公开信任锚，校验 PEM，分块传输，并核对客体内的字节摘要、证书数量和覆盖 `/etc/ssl/certs` 的临时内存挂载。原有磁盘证书库保持完整，持久化 profile 也一样；临时 CA 内容在 QEMU 退出后消失。此功能不捆绑或下载根证书，不修改宿主信任设置，也不复制私钥或客户端凭据。具体信任哪些 CA 由配置的 Python 信任库决定，不一定与 macOS 钥匙串相同。

选项默认 `off`。生成本地启动入口时添加 `--ca-certificates host` 可保存此选择。证书、主机名与有效期校验继续生效。原版 OpenSSL 协议能力和 WebKit 渲染限制仍然存在；TLS 证书通过不代表现代网页已经能正常显示或使用。

[证书验证记录](certificates-validation.json)覆盖生成的快捷入口界面回归、原版浏览器显示有效 HTTPS 页面，以及拒绝自签名证书站点。百度页面渲染的独立适配见下文。

## 原版浏览器渲染

使用 `HARMATTAN_UI_NETWORK=user` 的 UI 启动现会为原版 Grob 0.73.2 / libgrob-qtwebkit 0.73.0 准备限定范围的软件合成适配。浏览器的页面加速合成可能在没有当前上下文时进入 SDK GLES 包装层，加载百度时因此崩溃。适配通过原版 WebKit 的偏好设置接口关闭页面加速，并调用读取接口确认生效。JavaScript 设置、TLS 校验和 GLES 错误处理保持原样。

只有固定版本浏览器的桌面和 D-Bus 入口会通过临时内存挂载接入包装脚本。磁盘上的原始内容保持完整，持久化 profile 也一样。每次启动校验可执行文件、实际 WebKit 库链接及辅助库身份，其他应用不会继承该浏览器预加载库。未知版本会明确失败，不套用固定 ABI。构建器和发布辅助库清单已包含新的 ARM 辅助库；已下载的旧预览应用不会随源码自动更新。

[浏览器验证记录](browser-validation.json)覆盖 Web 图标/D-Bus 启动、百度 HTTPS 首页、原版键盘文字输入、有效 HTTPS 页面、自签名证书拒绝和联合 UI 回归。百度搜索结果及广泛的现代 JavaScript/CSS 兼容尚未通过：此前的搜索探针停留在加载页。这项适配不会把历史 WebKit 引擎升级为现代浏览器。

## 应用边界

此项恢复 SDK 以太网和 IP 访问。量产机 Wi-Fi 扫描、蜂窝、原版连接管理服务图及状态栏联网指示仍属独立工作。即使直接 socket 可用，依赖这些服务的应用仍可能显示离线。界面不伪造 Wi-Fi 或移动信号。

旧 TLS 库、过期证书、已停运接口和现代网页要求，也会独立影响旧浏览器或应用。此改动不会关闭证书校验，也不代表任意三方应用兼容。已测构建与范围见[验证记录](networking-validation.json)。
