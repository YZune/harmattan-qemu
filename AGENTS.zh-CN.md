# Agent 工作说明

[English](AGENTS.md) · [构建说明](docs/building.zh-CN.md) · [贡献指南](CONTRIBUTING.zh-CN.md)

仓库级 agent 入口是 `AGENTS.md`，本文件是它的中文译本，两者应同步维护。不会自动发现 `AGENTS.md` 的工具，需要显式指定读取入口。环境变更、提交、推送和 Pull Request 应遵循用户当前任务范围及已有授权；本文件本身不构成发布授权。

## 从这里开始

1. 在本 checkout 中工作，即使它嵌套在另一个研究仓库内。先检查 `git status --short --branch`、相关差异、`python3 --version` 和 `uname -sm`，保留无关修改及本地输入。
2. 下列命令使用 Python 3.12 或更新版本。先选择已安装的解释器；工具选择与依赖见构建说明。`HARMATTAN_PYTHON` 选择 shell 构建及启动脚本使用的解释器，不会改变下面直接调用的 `python3`。
3. 阅读[架构](docs/architecture.zh-CN.md)了解补丁归属，阅读[状态](docs/status.zh-CN.md)了解当前限制，然后按任务选择必要验证：

| 任务 | 前提与验证 |
| --- | --- |
| 文档或发布元数据 | 检查链接、发布内容和差异，无需重建模拟器 |
| 主机工具、验证器及测试 | Python、C 编译器、Perl；先运行相关 unittest，行为改动再运行主机测试套件 |
| QEMU/DGLES 补丁 | 原生 ARM64 macOS、宿主工具及固定源码归档；干净源码构建与相关图形检查 |
| 客体行为或交互 UI | 上述条件，再加 APFS、macOS 图形会话、支持 ARM 的 LLVM/lld、debugfs 和准备好的客体输入；运行相关客体诊断 |

Linux 可运行可移植主机测试，并跳过 AppKit 测试；完整模拟器运行目前面向 Apple Silicon macOS。`check-environment.py` 是完整构建的前提检查，其中缺少 Mac 或归档的结果不妨碍 Linux 上的纯源码贡献。它只检查文件存在及工具发现，不验证摘要、盘内内容、APFS 行为或编译器能力。

## 无需镜像的检查

以下检查不需要固件、SDK 安装器、客体镜像或机身素材。macOS 原生测试需要 Xcode Command Line Tools，本地 socket 测试需要 Unix socket 权限。

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py' -v
git ls-files '*.sh' | while IFS= read -r script; do
    sh -n "$script" || exit 1
done
python3 scripts/check-public-tree.py
git diff --check
```

发布检查使用 Git 列出的路径，读取当前工作区内容。新增文件应明确暂存后再检查，才能纳入检查范围。准备提交时审阅 `git diff --cached`、运行 `git diff --cached --check`，确保暂存内容与受检内容一致。没有 Git 元数据的源码归档中，检查器会扫描未忽略的文件；此时应直接检查 shell 文件的语法。

## 按任务需要构建与运行

按[构建说明](docs/building.zh-CN.md)准备工具和准确输入布局，[inputs.json](docs/inputs.json)标识归档和客体文件。先运行 `python3 scripts/check-environment.py`，需要客体运行时加 `--guest`。不要通过修改固定版本或摘要来绕过缺失或不匹配的输入。

前提满足后，如需一次完整的原生干净构建：

```sh
mkdir -p extracted
export HARMATTAN_PORT_WORKSPACE="$(mktemp -d "$PWD/extracted/agent-qemu.XXXXXX")"
export HARMATTAN_DGLES_WORKSPACE="$HARMATTAN_PORT_WORKSPACE/dgles2-host"
export HARMATTAN_DGLES_ROOT="$HARMATTAN_DGLES_WORKSPACE/gles-libs-1.4.2/dgles2"
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py --workspace "$HARMATTAN_DGLES_WORKSPACE"
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
```

后续运行应保留完全相同的工作目录及工具选择。Agent 的 shell 调用可能属于不同进程，应重新传入相同环境变量，不能假定上次 export 会保留。首次 QEMU 配置可能需要网络获取固定的 Meson 子项目；获取中断留下不完整源码时，保留失败结果，并换新工作目录重试。

客体输入准备好后，按所需覆盖范围选择命令：

```sh
# 有界客体回归，完成后退出。
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
# 带 Cocoa 窗口的有界回归。
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-diagnostic
# 交互会话；等待 READY 后再输入。
sh scripts/harmattan-qemu/run-arm64-ui.sh
```

不要每个任务都运行三种模式。准备输入前，先阅读[资源获取与准备指南](docs/guest-inputs.zh-CN.md)，其中说明准确原始材料及 `scripts/prepare-guest.py`。该脚本拒绝原始材料不匹配或输出目录已存在的情况，只写新建的派生工作目录。缺少输入时，明确报告缺项，并完成不依赖它的源码工作，不得声称客体已经运行。从用户提供的研究目录初次导入时，先预览 `scripts/import-local-inputs.py <source-workspace>`，仅在已授权的环境准备任务内使用 `--apply`。该工具拒绝覆盖现有目标，不是同步工具。

预编译分发工作先阅读[发行说明](docs/releases.zh-CN.md)。`scripts/release/` 负责打包、原生首次启动选择器和已准备磁盘导入。私有 Python 与预编译辅助程序消除使用者侧的编译依赖，不会重建零售固件。发布前验证搬移、源码及许可完整性和相关客体路径。沿用用户已有授权；默认仅发布源码的边界不禁止用户明确要求且经过检查的二进制发行。

## 修改归属

- `ports/qemu-n00/`：维护中的 QEMU 补丁和外壳视图源码。保留构建脚本的补丁顺序；只在解包树中修改，无法经过干净构建保留下来。
- `ports/dgles2/`：DGLES 补丁，应用到自己的固定归档，不应用到 QEMU 树。
- `scripts/harmattan-qemu/`：构建器、启动器、局部客体辅助代码、QMP 控制器及 `tests/`。沿用相邻代码和既有标准库、工具模式，保留源码及 ABI 检查和明确的失败处理。
- `docs/`、根目录 Markdown、`.github/`：公开文档和贡献设施。中英文同步更新，命令变化时同步维护本说明。

保留原版客体 UI 语义与来源署名，不编造设备遥测，不用模拟数据替换产品行为。不要只为通过而放宽 GPU、生命周期、身份、像素或命令失败的验证器；变更预期时应说明依据，并保留相关负例。

## 本地数据与贡献边界

- `downloads/`、`extracted/` 已忽略，但可能含有不可替代的输入和活动运行。避免整体清理、重写历史、广泛终止进程或暂存无关文件；只跟踪并清理本任务创建的进程与产物。
- 原生启动器默认使用一次性快照。显式指定 `HARMATTAN_USER_PROFILE` 可使用带排他锁、正常退出前执行客体写盘的私有持久磁盘，见[存储说明](docs/storage.zh-CN.md)。诊断继续使用独立磁盘。不要改用历史上持久写盘的 x86/Rosetta 启动器 `run-pr13-ui.sh`。
- 客体 overlay 应用脚本会写入客体系统目录，不能在宿主或真机上执行。克隆基础输入前应确保没有进程写入它们。
- 固件、SDK 安装器、镜像、字体、独立素材、凭据、个人数据库、内存转储及私人路径不能进入提交。精选运行截图在发布检查器中有明确路径和摘要，并有[采集说明](docs/screenshots/README.zh-CN.md)。
- 保留继承的许可声明及 [NOTICE](NOTICE)。明确暂存文件，贡献时使用[本地开发管理](docs/development.zh-CN.md)中的功能分支及 PR 流程。尊重当前任务已有授权，不额外增加常规审批步骤。

## 完成报告

说明改动、实际执行的命令、结果，以及未覆盖或受阻的部分。区分主机测试、干净源码构建、原生图形执行、无窗口客体、Cocoa 窗口和真实输入。QMP 截图及客体 RAM 采样不测量屏幕 FPS；历史记录只能作为参考，不能充当本次运行证据。不要将原始日志或机器专用路径复制进公开文档。
