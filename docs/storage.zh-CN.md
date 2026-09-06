# 持久用户档案

[English](storage.md) · [构建](building.zh-CN.md) · [联网](networking.zh-CN.md)

显式选择用户档案后，客体系统分区、已安装的软件包及 home 内已保存文件可跨启动保留。源码启动器默认仍使用一次性快照。使用档案前需重新构建 Cocoa interaction：

```sh
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" sh scripts/harmattan-qemu/run-arm64-ui.sh

# 下次继续选择同一目录；联网可单独开启。
HARMATTAN_USER_PROFILE="$PWD/extracted/profiles/daily" HARMATTAN_UI_NETWORK=user sh scripts/harmattan-qemu/run-arm64-ui.sh

# 自建独立档案：两次持久启动，再检查快照隔离。
sh scripts/harmattan-qemu/run-arm64-ui.sh --storage-diagnostic
```

第一次启动会从已准备底盘创建只读 APFS 克隆，并建立虚拟容量 32 GiB 的私有 qcow2 写入层。后续启动复用该写入层；更改来源镜像环境变量不会替换已有档案。原始输入磁盘保持独立。另选目录可建立另一份档案，不要选择已有无关文件夹或修改档案的 backing 文件。

控制器与 QEMU 共同持有档案锁。即使前一个控制器意外退出，第二个启动器也不能同时写同一磁盘。正常退出的档案在再次启动前，会将当前写入层 APFS 克隆为 `checkpoint.qcow2`。异常退出后保留原有检查点及当前磁盘供日志恢复，不会静默回滚用户的较新数据。

## 退出与恢复

先在应用内保存，再关闭 Cocoa 窗口，或在 `READY` 后按 Ctrl-C。控制器执行客体 `sync`、暂停 CPU、退出 QEMU，检查 qcow2 结构并刷新宿主文件后，才记录正常退出。启动期间关闭 Cocoa 窗口会等待启动检查完成。外部直接发送 QMP quit、强制退出、崩溃或在 `READY` 前中断，可能使档案标记为异常退出。下次启动的文件系统日志恢复，与应用能否恢复未保存内容是不同事项。

档案会话为 `/tmp` 和 `/var/run` 挂载全新、限制容量的客体 tmpfs，避免旧 socket/PID 文件影响下次启动。应用数据应保存在客体正常持久位置，通常为 `/home/user`。

关闭档案后备份整个目录；`disk.qcow2` 依赖 `base.raw`。检查点用于磁盘恢复，不是 CPU/RAM 快照或独立备份。移动档案时保留两层文件。此功能尚不代表自动回滚、任意虚拟机保存/恢复、挂起/唤醒或断电持久性已经成立。

诊断会拒绝 `HARMATTAN_USER_PROFILE`，使用自建磁盘。重新构建的预编译应用也可通过内部运行命令的 `run --profile <目录>` 显式选择档案；已经下载的预览应用需要先重新构建。普通应用入口保持原有快照默认值。已测行为见[验证记录](storage-validation.json)。
