# 原版开机画面

[English](boot-animation.md) · [构建指南](building.zh-CN.md)

## 为什么保留启动检查

原生启动器在最小救援环境中依次启动原版 Xorg、主题服务、System UI、合成器、键盘与 Home。bootstrap/theme/compositor/home/settled/final 阶段同时承担启动和检查工作。控制器核对可执行文件身份、GPU 输出、稳定的 Home 像素及输入屏障，全部通过后才报告 `READY`。这些中间画面不需要展示给用户。本次保留全部验证器和现有等待，包括合成器 8 秒、Home 25 秒和稳定阶段 5 秒；这是显示改动，不代表已经测得启动加速。

## 原始素材与显示行为

支持的 PR1.3 根文件系统包含：

- `/usr/share/MProgressIndicator/themes/mprogressindicator.conf`：选择 `opengl` 主题。
- `/usr/share/MProgressIndicator/themes/opengl/MainAnimation_LowNoise.mp4`：449,012 字节，扩展名虽为 MP4，实际采用 RIFF/AVI 容器；854 × 480 的 MPEG-4 视频，帧率 24000/1001，约 4.2 秒，带 MP3 音轨。
- `/etc/init/xsession/mprogressindicator.conf`：启动原版 X11 `MProgressIndicator`，收到 `DESKTOP_VISIBLE` 后停止。
- `/etc/init/xsession/mpi-animation.conf`：通知同一进程开始播放 Nokia 动画。

视频 SHA-256 为 `19e311e44e102c84d75fe921f6af3af212173a86cbb549714ee1118b8d4ea40a`。源码及应用包不包含视频、图片、标志或解码帧。启动器从本次私有 raw 磁盘克隆读取这一项资源，精确校验字节后，将原有 MPEG-4 码流重新封装成不含音轨的 MP4，供 AVFoundation 播放。此过程只使用 Python 标准库，不重编码、不新增解码器。有限的只读 ext4 读取器仅支持已准备的 PR1.3 布局，拒绝不支持的映射及特性，不跟随符号链接，不挂载文件系统，也不重放日志。数据结构依据 [Linux ext4 文档](https://www.kernel.org/doc/html/latest/filesystems/ext4/)。

Cocoa 覆盖层在启动早期显示视频首帧，开始启动 Home 时按原速播放一次，结束后保持末帧直到检查完成。画面跟随显示旋转，保持原始比例并以黑色补边。视频静音播放；客体音频硬件仍未实现。这是通过 AVFoundation 复用原版视觉素材，不运行原版 MPI 进程，也不代表恢复了量产 Upstart 或设备服务。

覆盖层背后的客体 framebuffer 持续正常渲染，QMP 截图仍获取真实客体像素。全部现有启动检查通过后，控制器请求揭开覆盖层，收到 Cocoa 确认后再释放原有客体输入屏障。视频结束本身不能开放输入或报告就绪。发生错误时保留运行日志并使启动失败，不显示成功状态。

## 构建与诊断

从新解压的源码构建 `--cocoa-interaction`；最后一项维护补丁添加 Cocoa 覆盖层与系统 AVFoundation/CoreMedia 框架。运行应用不新增解码器、Python 包、debugfs 或独立素材依赖。预编译打包器会在重建发布包时收录这些代码；已下载的应用不会因此被修改。

正常交互启动默认开启覆盖层。`HARMATTAN_UI_BOOT_ANIMATION=off` 可直接显示中间 framebuffer 以便诊断；重新打包的应用也支持 `run --no-boot-animation`。有界诊断保持原先的显示方式。应用 `HARMATTAN_UI_SPLASH` 与开机视频无关，继续关闭。

本次运行的 `ui/boot/` 保存私有提取视频、阶段请求与原生确认文件，`ready.json` 记录视频摘要和桌面交接成功。运行目录里的视频仅转换封装，`playback_sha256` 单独标识它，避免与原始资源摘要混淆。这些属于本地运行证据，不应发布。宿主测试使用合成文件系统及代码生成的视频，并覆盖损坏元数据、素材变化和过早交接等失败情况。

[验证记录](boot-animation-validation.json)包含干净原生构建、257 项宿主测试通过、原视频与转换封装后的视频包和解码帧完全一致，以及可见 Cocoa 启动、原生鼠标输入 `2+3=5` 和正常退出。它不代表启动提速、完整产品启动或新打包应用已经通过验证。
