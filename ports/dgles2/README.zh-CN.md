# DGLES 宿主后端

[English](README.md) · [构建指南](../../docs/building.zh-CN.md)

将 `gles-libs-1.4.2-cocoa-fbo.patch` 应用到固定 PR1.3 源码归档中的 `gles-libs-1.4.2/`。它是宿主图形库补丁，不属于 QEMU 设备补丁序列。

构建脚本为 `scripts/harmattan-qemu/build-dgles2-host.sh`，只在本地构建，不全局安装。`smoke-dgles-host.py` 在 macOS 图形会话中通过原生库验证 GLES1/GLES2 离屏渲染。

显式路径使用 `DGLES2_COCOA_FBO=1`、`DGLES2_FRONTEND=offscreen`、`DGLES2_BACKEND=cocoa`。其他变体、通用并发、跨上下文 surface 和完整 GLES 一致性尚未验证。保留各文件许可，不能将整个归档视作统一 MIT，详见[来源](../../docs/sources.zh-CN.md)。

Linux x86_64 构建器在 Cocoa 补丁后应用 `gles-libs-1.4.2-linux-osmesa.patch`，选择 `DGLES2_BACKEND=osmesa`，关闭 Cocoa/X11/GLX/WGL。它使用归档内的 ABI 头文件及 `libOSMesa.so.8`，详见 [Linux 指南](../../docs/linux.zh-CN.md)。两个后端均需显式本地构建。

Linux smoke 检查 GLES1/GLES2 像素、缩放和所有权失败、原生解绑、两种释放顺序、已保护的废弃像素内存，以及进程退出前的线程清理。QEMU 独立的提前清理补丁在 Mesa 的 `atexit` 释放前停止图形线程。这些检查不代表通用跨上下文共享或完整 GLES 一致性。
