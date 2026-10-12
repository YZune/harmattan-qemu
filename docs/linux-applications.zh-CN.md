# Linux 原版应用实测

[English](linux-applications.md) · [原生窗口](linux-native.zh-CN.md) · [验证记录](linux-applications-validation.json)

原版日历可以在正常退出、重启客体后保留本地事件，原版任务卡片可以恢复 Notes 和计算器，并单独关闭一张卡片。Clock 已验证的范围较小，Gallery 图片浏览仍然阻塞。这些检查于 2026-10-11 在 Linux 原生窗口中完成，使用 [`3537ae9`](https://github.com/YZune/harmattan-qemu/commit/3537ae96371b8ba2f550bbd54aee91eedc65502b) 对应源码树。

| 原版应用或视图 | 实测结果 | 主要限制 |
| --- | --- | --- |
| Calendar（`organiser`） | 新建全天本地事件、修改标题和日期、重开界面，并在新客体进程中恢复编辑后的事件 | 需要屏幕键盘；只测了一条无提醒事件 |
| Clock | 从 Home 打开、观察本地时间推进、打开闹钟编辑页后取消 | 未验证保存闹钟或多城市操作 |
| Gallery | 可以打开，但两张合成图片导入后，所检查的两个视图仍显示 **No items** | Tracker 服务名注册遭拒；发现、缩略图和浏览未通过 |
| Home 任务卡片 | 恢复已保存的 Notes 和结果为 `5` 的计算器，单独关闭计算器，继续编辑 Notes，再打开计算器显示 `0` | 单次临时会话；卡片编辑后出现 Notes 缩略图变暗的瑕疵 |

这些是通过 Godot 中的桌面鼠标、键盘事件操作的真实客体应用，没有重绘替代界面。宿主为 Linux x86_64，使用 QEMU 9.1.3、Godot 4.6.3 和 DGLES/OSMesa 软件渲染。客体网络及音频关闭。应用身份与输入摘要见验证记录。依赖库存在不代表全部原版服务均可用。

## 准备有界离线会话

先完成 [Linux 构建与客体准备](linux.zh-CN.md)、DGLES smoke 检查及[原生窗口前置条件](linux-native.zh-CN.md#构建与启动)。保留 smoke 实际输出的准确 renderer 字符串。从图形桌面的终端进入仓库根目录，沿用构建指南中的环境变量。日历重启检查应选择**全新专用档案**及新的输出目录：

```sh
python3 -B scripts/harmattan-qemu/run-linux-ui.py \
  --build-root "$HARMATTAN_LINUX_BUILD" \
  --dgles-runtime "$HARMATTAN_DGLES_ROOT/objs-x86_64" \
  --prepared-root extracted/guest-from-original-media-linux \
  --renderer 'llvmpipe (LLVM 19.1.7, 256 bits)' \
  --compositor-fbo-fix --mode live --frontend "$(command -v godot)" \
  --profile "$PWD/extracted/profiles/linux-app-check" \
  --output "$PWD/extracted/linux-app-check-01" --timeout 1800
```

上面的 renderer 是本次实测值；若本机 smoke 输出不同，替换为准确结果。[合成器修正](gles-framebuffers.zh-CN.md)已是受支持的显式选项，保留原有身份和调用点检查。1–1800 秒 live 预算包含启动时间。等待 **Live** 后再操作，先在应用内保存，再于时限前点击前端 **Quit**。

第二次启动沿用同一档案，将输出换成 `extracted/linux-app-check-02` 等新路径。检查 `launch-result.json`、`ui/startup-result.json` 和 `ui/interactive-exit.json`：档案验收需要进程正常退出、`storage.guest_synced=true`、`storage.state=clean`，并实际看到数据保留。仅启动成功不能证明应用已保存数据。

首次创建档案需要稀疏基础盘副本、可写盘和 checkpoint 的空间。遵循[持久文件说明](linux-native.zh-CN.md#可选文件持久化)，保持基础输入静止，仅在档案关闭后备份整个目录。正常退出后文件保留不代表断电耐久或 CPU/RAM 存档。若只做临时任务卡片检查，去掉 `--profile`，另选新的输出目录。此模式会丢弃客体保存的改动，也不走档案 sync/checkpoint 流程。

## 日历本地事件

1. 从 Home 打开 Calendar；若提示账户设置，选择 **No Thanks**。
2. 选择日期并新建事件，用原版**屏幕键盘**输入合成标题。选择 **All day**、**Personal**、**Not repeated**、**Reminder None**，然后保存。
3. 打开事件，选择铅笔编辑控件，修改标题和日期，再次保存。等详情画面稳定后核对。
4. 使用原版顶部边缘关闭手势，从 Home 重开 Calendar，分别检查新日期和旧日期。
5. 正常退出整个原生会话。用同一档案、新输出目录启动新的 launcher 进程，再次查看事件。

实测事件从 2026-10-15 的 **Calendar alpha** 改为 2026-10-16 的 **Calendar alpha revised**。重开界面后，旧日期显示 **No events**，新日期显示一条匹配的全天事件。新 QEMU 进程启动后，准确的修改后标题和日期仍可见。这是对应界面的观察结果，没有枚举整个数据库。应用界面关闭、重开之外，未单独测量应用进程是否销毁。

Calendar 键盘带有 **Done** 动作键。已合入的宿主键盘识别器尚不认识此布局，所以这次没有用宿主字母输入。请分小组点击原版屏幕按键并核对最终文字。快速批量点击曾丢失字母，即使指针请求已确认；原因仍未定位。本次未使用退格，已知快速退格后的大小写问题也未因此修复。后续本地 Done 布局实验尚未合入，不属于本指南。

未测试重复事件、提醒、声音、锁屏唤醒、账户和日历同步。

## Clock 检查

从 Home 打开 Clock。实测模拟表盘和状态时间在 10 月 11 日从 14:49 推进到 14:51。原版 **+** 控件打开闹钟标题、时间编辑页；点击 **Cancel** 返回空闹钟列表。没有保存闹钟，也没有修改系统日期、时间或时区设置。

在此版本的有界检查中没有找到多城市管理入口，因此没有完成原计划的城市新增、删除和重启检查。这不是已确认的模拟器故障，也不是针对全部 N9 应用或版本的结论。launcher 现有的宿主时钟同步不证明原版 `timed` 服务、闹钟触发、声音或唤醒可用。由于没有创建可持久保存的城市或闹钟状态，未为 Clock 再启动第二次客体。

## Notes 和计算器任务卡片

1. 在 Notes 中保存合成笔记，返回 Home，打开计算器并计算 `2+3=5`。
2. 返回 Home，水平滑动到原版任务卡片页，依次选择两张卡片，检查恢复后的界面。
3. 长按计算器卡片，直到出现原版 **X**、**Done**、**Close all** 控件。只点击计算器的 **X**，然后点击 **Done**。
4. 恢复 Notes，编辑并保存。返回 Home，从图标打开计算器，观察实际数值，不预设已关闭应用会保留状态。

实测通过卡片恢复了 **Multitask alpha** 和计算器结果 **5**。关闭计算器卡片后，Notes 仍可编辑并保存为 **Multitask alpha saved**。从 Home 重开计算器显示 **0**。这证明了观察到的界面关闭、重开流程；没有跟踪应用 PID。

退出卡片编辑模式后，剩余 Notes 缩略图变暗，右上角有亮色矩形。恢复 Notes 后完整应用界面正常，编辑、保存再返回后缩略图恢复正常。该可见瑕疵尚未修复。本项只使用单次临时会话，不宣称重启或未保存文字保留。

## Gallery 仍然阻塞

两张明确标示为合成测试的 PNG 导入专用档案后，原版 Gallery 可以打开。人脸识别提示已取消，所检查的两个主视图均停留在 **No items**。原版 Tracker 日志报告在注册 `org.freedesktop.Tracker1` 时遭遇 `org.freedesktop.DBus.Error.AccessDenied`；救援会话无法解析所需的原版 Aegis 凭据。图片发现、两张缩略图、逐张打开、前后切换及客体重启后访问均未通过。首个检查失败后没有再重启客体。

该次 Gallery 运行还记录了五条 XServer `BadValue` 和原生窗口初始绘制异常。正常拖动标题栏调整大小后窗口恢复可见；原因没有定位或修复。客体图形故障计数为零不等于前端没有错误。

后续独立、**未合入的安全研究**在原版 `aegisSessionOpen()` 的 platsec 设备警告处停止，尚未发起 Tracker 激活。该次诊断的 **Tracker 激活请求为零**，没有取得 Tracker 凭据或通过总线归属检查。该警告本身不能证明整条原版登录链必然失败：静态检查显示警告分支仍会继续。这次后续诊断不替代早先 Gallery 的拒绝结果，也不构成可用的 Gallery 修复。它不属于上面的普通复现步骤；本文不提供安全加载器、权限或策略绕过方法。

## 证据范围

日历的两次会话、Clock、Gallery 和任务卡片会话都以 QEMU、controller、前端退出码 0 结束，图形工作线程已回收，renderer faults/rejects 计数为零。日志另保留原版已知的重复 `eglTerminate(NULL)` 拒绝。日历、Clock、Gallery 档案完成 sync 并报告 clean；临时任务卡片会话明确报告 `guest_synced=false`。

运行后原始媒体与 prepared 输入 SHA-256 均匹配。既有档案已保留；验证记录区分全文件摘要与仅元数据检查。私有日志、截图和合成档案不放入本源码分发。记录只包含身份和有界结果，不含客体二进制、磁盘、个人数据或私有宿主路径。

这些应用验收不需要生产代码改动，也没有为此新跑 macOS 客体或完整主机回归套件。结果不证明全部应用、完整零售安全/设备服务、长期稳定性或物理输入延迟。
