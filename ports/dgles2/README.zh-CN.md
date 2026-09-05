# 原生 macOS DGLES 后端

[English](README.md) · [构建指南](../../docs/building.zh-CN.md)

将 `gles-libs-1.4.2-cocoa-fbo.patch` 应用到固定 PR1.3 源码归档中的 `gles-libs-1.4.2/`。它是宿主图形库补丁，不属于 QEMU 设备补丁序列。

构建脚本为 `scripts/harmattan-qemu/build-dgles2-host.sh`，只在本地构建，不全局安装。`smoke-dgles-host.py` 在 macOS 图形会话中通过原生库验证 GLES1/GLES2 离屏渲染。

显式路径使用 `DGLES2_COCOA_FBO=1`、`DGLES2_FRONTEND=offscreen`、`DGLES2_BACKEND=cocoa`。其他变体、通用并发、跨上下文 surface 和完整 GLES 一致性尚未验证。保留各文件许可，不能将整个归档视作统一 MIT，详见[来源](../../docs/sources.zh-CN.md)。
