# 有界 GLES2 帧缓冲调用封送

[English](gles-framebuffers.md) · [Linux 构建与客户机准备](linux.zh-CN.md) · [Linux 原生窗口](linux-native.zh-CN.md) · [验证记录](gles-framebuffers-validation.json) · [架构](architecture.zh-CN.md)

这个实验性阶段为现有 ARM32 客户机到宿主的 GLES2 桥接增加帧缓冲对象（FBO）和渲染缓冲对象（RBO）调用。它通过 DGLES 支持有明确限制的离屏渲染子集。原始线协议、原始库及一次限定范围的 Linux 原生交互运行已通过；这不代表完整 GLES2 实现、SGX 仿真或任意应用兼容性。

## 已实现的接口

维护中的 `qemu-9.1.3-n00-gles-render.patch` 提供 `n00_gles_fbo.inc`，封送以下 14 个线协议方法：

| 操作 | 方法 |
| --- | --- |
| 名称与生命周期 | `glGenFramebuffers`、`glDeleteFramebuffers`、`glGenRenderbuffers`、`glDeleteRenderbuffers` |
| 绑定与对象识别 | `glBindFramebuffer`、`glBindRenderbuffer`、`glIsFramebuffer`、`glIsRenderbuffer` |
| 附件与存储 | `glFramebufferTexture2D`、`glFramebufferRenderbuffer`、`glRenderbufferStorage` |
| 状态与查询 | `glCheckFramebufferStatus`、`glGetFramebufferAttachmentParameteriv`、`glGetRenderbufferParameteriv` |

现有 `glGetIntegerv` 路径还处理 `GL_FRAMEBUFFER_BINDING`、`GL_RENDERBUFFER_BINDING` 和经过限制的 `GL_MAX_RENDERBUFFER_SIZE`。标量输出和对象名称数组采用经过检查的客户机内存复制及小端线协议数值。具有五个参数的纹理附件调用沿用 ARM 栈 ABI，并检查地址计算是否溢出。

每个 GLES 上下文分别维护帧缓冲和渲染缓冲记录。客户机对象名称映射到宿主 DGLES 名称，因此客户机无法通过猜测名称访问或删除 DGLES 私有的默认帧缓冲。客户机帧缓冲零选择现有默认绘制表面；绑定查询返回客户机名称。生成的名称与通过绑定非零名称创建的对象遵守相同限制。上下文之间的共享语义不在本阶段已验证范围内。

## 限制与生命周期

| 资源 | 限制 |
| --- | --- |
| 有效帧缓冲名称 | 每个上下文 128 个 |
| 有效渲染缓冲名称 | 每个上下文 128 个 |
| 单次生成／删除调用的名称数组长度 | 0–128 |
| 渲染缓冲尺寸 | 每个维度不超过 4096，且不超过后端报告的最大值 |
| 渲染缓冲存储预留 | 每个上下文 64 MiB，按宽 × 高 × 4 字节计费 |
| 附件点 | `GL_COLOR_ATTACHMENT0`、`GL_DEPTH_ATTACHMENT`、`GL_STENCIL_ATTACHMENT` |
| 非零纹理附件 | `GL_TEXTURE_2D`，第零级 |

存储计费是逻辑预留策略，不是宿主物理内存上限，也不测量 Mesa 的实际分配。它不包含纹理、驱动元数据、填充或其他图形资源。所有受支持的渲染缓冲格式均按每像素四字节计费。接受的存储格式为 `GL_RGBA4`、`GL_RGB5_A1`、`GL_RGB565`、`GL_DEPTH_COMPONENT16` 和 `GL_STENCIL_INDEX8`。

删除渲染缓冲会移除其有效客户机名称，并将它从当前绑定的帧缓冲上分离。其他帧缓冲上的附件仍可保留旧宿主对象及其全部预留。只有最后一个附件消失时，例如替换、分离或删除帧缓冲后，才释放该保留对象的预留。复用客户机名称会创建独立对象。记录空间可容纳 128 个有效渲染缓冲以及最多 384 个由附件保留的对象；这不会提高有效名称数或存储上限。

生成名称前会预先检查完整输出范围；分配失败或随后客户机写入失败时回滚宿主分配。无效计数、目标、附件枚举、格式、尺寸和不受支持的非零纹理级别都会被拒绝。对象为零的附件调用执行分离，并忽略不再使用的对象专属目标／级别参数。附件操作失败不会释放原有渲染缓冲预留；尺寸调整失败也不会仅根据请求就增加或释放预留。参数拒绝保留之前尚未读取的 GL 错误。

## 验证配置

请分别运行这些配置。验证器要求匹配所选标记、精确调用／拒绝／故障总数、真实渲染器身份、预期像素和工作线程回收结果；负面测试中有意触发的拒绝不能在普通 UI 运行中被放行。

- 原始线协议 `--render --fbo-api` 配置检查对象创建、绑定、查询、纹理／深度及颜色／深度附件、清除／回读、删除及返回默认帧缓冲。共享 FBO 测试在现有着色器／纹理／顶点和显示检查之外，验证 24 个 RGBA 像素及输出边界哨兵。
- 增加 `--negative` 选择专用畸形输入配置，检查无效客户机指针、计数、上限、参数、输出保留及错误恢复。预期失败仅适用于此配置。
- 原始库 `--fbo-api` 配置链接固定的客户机 EGL/GLES 库，并在原始 Xorg 内运行。分别使用 `--noxshm 0` 检查 XShm、`--noxshm 1` 检查 XImage。它验证已映射库及其身份、实际共享内存使用、同一 FBO 测试及两帧显示输出。`--shell-api` 是独立且互斥的配置。
- 宿主测试在有界模拟 GL 后端上执行维护中的封送代码，并启用 AddressSanitizer 与 UndefinedBehaviorSanitizer。覆盖小端转换、分配回滚、首次绑定创建、数量上限、尺寸调整计费、标量输出边界、上下文隔离、栈地址溢出拒绝、延迟释放及名称复用。这些测试不能替代真实 Mesa 或客户机运行。

原始客户机库重复调用 `eglTerminate(NULL)` 的已知结果仍由公共库验证器明确检查。这个既有终止缺陷与 FBO 行为分别记录。

2026-10-10 的最终本地 Linux 探针运行得到以下结果：

| 配置 | 线协议调用 | 交换帧数 | 预期客户机内存故障 | 预期参数拒绝 |
| --- | ---: | ---: | ---: | ---: |
| 原始 FBO | 177 | 4 | 0 | 0 |
| 原始 FBO 负面测试 | 271 | 4 | 7 | 16 |
| 原始库，XShm | 142 | 2 | 0 | 0 |
| 原始库，XImage | 142 | 2 | 0 | 0 |

四次运行均检查了 24 个 FBO RGBA 像素及各自已有的显示检查，并回收全部图形工作线程。负面配置的 23 次有意失败包括交换帧缓冲／渲染缓冲绑定目标的两种情况，并验证被拒绝的调用保留原绑定。这些结果使用的 QEMU SHA-256 为 `3665576d27bf70b63cf94864f67e59ea246cbed8b76c6d01762e15f30bc6853e`；它们不能作为原生窗口验收。

使用 Python 3.12 或更新版本、`patch` 及能够正常运行 AddressSanitizer 和 UndefinedBehaviorSanitizer 的 `cc` 编译器，执行宿主封送检查：

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_gles_fbo_marshalling.py' -v
```

本地验证环境的 ptrace 限制要求设置 `ASAN_OPTIONS=detect_leaks=0`。该次运行保留地址／未定义行为检查，但未检查泄漏。宿主支持时应采用正常的 sanitizer 设置。

2026-10-10 的最终本地宿主完整测试集未通过：512 项测试中有四项错误、七项跳过，无断言失败。四项错误均来自 `test_arm64_splash`，原因是云端沙箱拒绝创建 AF_UNIX 套接字。八项 FBO 封送用例和六项窄范围合成器修正用例通过。本地结果不能作为 CI 或 macOS 运行时验收。

## 在 Linux 上复现

先完成 [Linux 源码构建、DGLES 冒烟测试与客户机准备](linux.zh-CN.md)，为修改后的补丁选择全新源码工作区。保留该指南中的 `HARMATTAN_PORT_WORKSPACE`、`HARMATTAN_LINUX_BUILD`、`HARMATTAN_DGLES_ROOT`、ARM 编译器及 `debugfs` 选择。使用 Python 3.12 或更新版本并安装 Pillow。以下命令从仓库根目录运行，仅使用静止的已准备基础镜像上的一次性覆盖层。

将 `HARMATTAN_FBO_RENDERER` 设为成功的 DGLES 宿主冒烟测试中独立观测到的完整渲染器名称。下值是 Linux 指南中的示例，不能代替对本机后端的实际观测。请整体运行下面的完整命令块：子 shell 将库／显示环境变量限制在探针运行中，不会影响之后的 Godot 原生窗口启动。

```sh
(
set -eu
export HARMATTAN_FBO_RENDERER='llvmpipe (LLVM 19.1.7, 256 bits)'
export HARMATTAN_FBO_PREPARED="$PWD/extracted/guest-from-original-media-linux"
export HARMATTAN_GLES_WIRE_DIR="$HARMATTAN_LINUX_BUILD/../hw/arm"
export HARMATTAN_ADAPTATION_LIBDIR="$HARMATTAN_FBO_PREPARED/overlay/usr/lib"
export HARMATTAN_PUBLIC_ROOTFS="$HARMATTAN_FBO_PREPARED/pr1.3-rootfs-qemu-rescue.ext4"
export LD_LIBRARY_PATH="$HARMATTAN_DGLES_ROOT/objs-x86_64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export LP_NUM_THREADS=2
export EGL_PLATFORM=surfaceless
sh scripts/harmattan-qemu/build-gles-guest.sh
sh scripts/harmattan-qemu/build-gles-public-guest.sh --fbo-api
export HARMATTAN_FBO_RUN="$(mktemp -d "$PWD/extracted/gles-fbo.XXXXXX")"
export MESA_SHADER_CACHE_DIR="$HARMATTAN_FBO_RUN/mesa-cache"
unset N00_GLES_TRACE_REJECTS

# Raw-wire positive and negative profiles, each with a fresh overlay.
for profile in render-fbo render-fbo-negative; do
    image="$HARMATTAN_FBO_RUN/$profile.qcow2"
    "$HARMATTAN_LINUX_BUILD/qemu-img" create -q -f qcow2 -F raw \
      -b "$HARMATTAN_FBO_PREPARED/harmattan-pr1.3.raw" "$image" 32G
    set --
    if [ "$profile" = render-fbo-negative ]; then set -- --negative; fi
    python3 -B scripts/harmattan-qemu/smoke-arm64-gles.py \
      --output "$HARMATTAN_FBO_RUN/$profile" \
      --probe "$HARMATTAN_PORT_WORKSPACE/guest-probes/smoke-gles-guest-$profile" \
      --render --fbo-api "$@" --renderer "$HARMATTAN_FBO_RENDERER" --timeout 300 -- \
      "$HARMATTAN_LINUX_BUILD/qemu-system-arm" -M n00-port-spike \
      -kernel "$HARMATTAN_FBO_PREPARED/zImage-2.6.32.26-qemu" \
      -append 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 hlt console=ttyS0,115200n8 omap3_die_id' \
      -drive "if=sd,format=qcow2,file=$image" \
      -snapshot -display none -no-reboot -nic none
done

# Original-library XShm (0) and XImage (1) profiles.
for noxshm in 0 1; do
    image="$HARMATTAN_FBO_RUN/public-$noxshm.qcow2"
    "$HARMATTAN_LINUX_BUILD/qemu-img" create -q -f qcow2 -F raw \
      -b "$HARMATTAN_FBO_PREPARED/harmattan-pr1.3.raw" "$image" 32G
    python3 -B scripts/harmattan-qemu/smoke-arm64-gles-public.py \
      --output "$HARMATTAN_FBO_RUN/public-$noxshm" \
      --probe "$HARMATTAN_PORT_WORKSPACE/guest-probes/smoke-gles-fbo-api-guest" \
      --fbo-api --noxshm "$noxshm" --renderer "$HARMATTAN_FBO_RENDERER" --timeout 300 -- \
      "$HARMATTAN_LINUX_BUILD/qemu-system-arm" -M n00-port-spike \
      -kernel "$HARMATTAN_FBO_PREPARED/zImage-2.6.32.26-qemu" \
      -append 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 hlt console=ttyS0,115200n8 omap3_die_id' \
      -drive "if=sd,format=qcow2,file=$image" \
      -snapshot -display none -no-reboot -nic none
done
)
```

探针构建脚本在所选工作区的 `guest-probes/` 内生成 `smoke-gles-guest-render-fbo`、`smoke-gles-guest-render-fbo-negative` 和 `smoke-gles-fbo-api-guest`。原始线协议探针无需客户机 sysroot 或 libc；公共库探针校验固定库输入，并只读已准备 rootfs，不作修改。第一个循环运行两种原始线协议配置，第二个循环运行两种原始库交换模式。四次运行均使用独立的覆盖层和输出目录。

遇到失败命令时应停止并检查，再决定是否继续。这些直接探针要求未旋转的 864×480 客户机显示；不要添加原生 UI 启动器的 `-rotate 270`。每个输出目录都必须是新目录。运行器将辅助程序上传到快照，通过标准输入输出使用 QMP，并使用权限为 0600 的串口 FIFO，不开放宿主控制监听端口。Linux 先采集作为权威数据的 PPM，再导出 PNG 并确认 RGB 像素完全相同。在本地查看生成的 `result.json`、`serial.log` 和 `qemu-stderr.log`；客户机镜像、可执行文件、原始日志及机器专属路径均不得进入 Git。

不提供 `--renderer` 时，探针运行器保留既有 `Apple` 默认值及套接字传输。本 Linux 路径不改变 macOS 默认行为，本阶段也未重新运行 macOS 运行时验证。

## 原始合成器修正与原生验证

一次原生 Notes 运行首先暴露了独立的原始合成器缺陷：`MCompositeWindowGroup::init` 调用 `glBindFramebuffer` 时将 `GL_RENDERBUFFER` 作为目标。严格 Quit 门禁正确判定失败，记录一次渲染拒绝、零图形故障。被检查的 `libmcompositor.so.1.1.3` SHA-256 为 `e9fcdb50530076abce62aaae65f5116a71badc283c89111a0d5e38f13b4a8c1b`。这个客户机调用方缺陷与补齐帧缓冲线协议方法是两个不同问题。

仅限 Linux 的 `--compositor-fbo-fix` 选项选择独立、限定在进程内的预加载辅助库。构建及启动检查固定原始库的完整哈希；辅助库检查已加载函数的入口及调用点指令。只有错误目标来自精确的 `init+0x74` 返回地址时，才将目标改为 `GL_FRAMEBUFFER`。其他调用原样转发，身份／ABI 不匹配时拒绝继续。原始库二进制及桥接对错误目标的拒绝行为保持不变。此选项默认关闭，不改变 macOS 默认行为。

满足[原生窗口前置条件](linux-native.zh-CN.md#构建与启动)后，使用 DGLES 冒烟测试中观测到的精确渲染器名称启动：

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --mode live --compositor-fbo-fix \
  --frontend "$(command -v godot)" --timeout 1800
```

2026-10-10 的受保护原生运行通过，且 `guard_observed=true`、`callsite_fix_observed=true` 均有实际记录。通过真实 Godot 窗口发送的操作系统桌面事件覆盖了 Notes 输入／保存 `Linux works AaZz`、新建／取消／再次新建并输入 `Fbo works`、Escape 返回 Home、重新打开草稿并保存两条笔记、鼠标边缘手势返回、Calculator `2+3=5` 及原生 Quit。输入审计共记录 103 个事件：102 个被接受，一个自动释放因 Quit 优先级被取消，并非输入文字失败。

QEMU、控制器及 Godot 均以代码零退出，前端自然结束。图形摘要记录 14,116 次调用、161 次交换、零故障、零渲染拒绝及工作线程全部回收。已准备基础镜像的元数据保持不变；本次运行未重新计算完整基础镜像哈希。这是限定范围的原生交互及生命周期证据，不是物理输入延迟、显示 FPS、性能提升、持久化存储或长时间运行验收。精确计数及分别记录的失败／通过阶段见[验证记录](gles-framebuffers-validation.json)。

## 拒绝诊断与剩余限制

针对性诊断时，在 QEMU／控制器调用上设置 `N00_GLES_TRACE_REJECTS=1`。它最多输出 64 行拒绝详情，随后输出一行抑制提示。每行包含客户端、API、ABI、调用编号、GL 错误和已保存的 `r0`–`r3` 值。它不会额外读取客户机内存、消费尚未读取的 GL 错误或放宽严格拒绝／故障门禁。此开关按环境变量是否存在判断：应取消设置以关闭；设为 `0` 仍会开启。普通的精确日志探针验证应在取消设置此开关后运行。

立方体贴图附件、非零纹理级别、扩展格式、多重采样、共享上下文语义、任意应用及长时间稳定性仍不在已验收范围内。本项工作不提供新的发布包、CI 或 macOS 运行时验收。
