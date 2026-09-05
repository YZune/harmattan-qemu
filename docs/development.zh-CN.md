# 本地开发管理

[English](development.md) · [构建](building.zh-CN.md) · [贡献指南](../CONTRIBUTING.zh-CN.md)

将 `YZune/harmattan-qemu` 的本地 checkout 作为后续 QEMU 补丁、辅助程序、测试和公开文档的维护入口。开发模拟器时，在编辑器或 Codex 中打开这个仓库根目录。

## 仓库与本地数据

| 位置 | 用途 | Git 管理方式 |
| --- | --- | --- |
| `ports/`、`scripts/` | 维护中的补丁、兼容辅助代码、构建及测试工具 | 在这里修改并提交经过审阅的文件 |
| `docs/`、根目录文档、`.github/` | 双语文档、精选截图、CI 及贡献模板 | 提交到开源仓库 |
| `downloads/` | 本地源码归档及自行提供的历史输入 | 已忽略；有保留价值的材料另行备份 |
| `extracted/` | 解包目录、构建、准备好的客体输入及运行产物 | 已忽略；部分输入目前还不能自动重建 |
| 独立的 Harmattan 研究仓库 | 源码考古、浏览器原型、历史证据及实验 | 独立本地历史，不会自动同步 |

公开仓库使用全新 Git 历史导出。即使它位于研究仓库的 `publish/harmattan-qemu` 中，也仍然是独立仓库，不是 submodule 或 worktree。在父仓库旧 `scripts/`、`ports/` 中的修改不会到达 GitHub。旧副本作为历史参考，后续模拟器功能统一在本 checkout 开发。后来产生的研究修复逐项审阅、迁移，并保留来源；不要为了同步目录而合并无关的 Git 历史。

父仓库可以通过本地 `.git/info/exclude` 忽略 `/publish/`，避免误暂存嵌套仓库。执行 Git 命令前确认所在仓库根目录，并检查 `git status`。

## 一次日常修改

从干净工作区开始，将下面的示例分支名换成实际改动：

```sh
git status --short --branch
git switch main
git pull --ff-only
git switch -c codex/example-fix
```

修改维护中的源码或补丁文件；涉及文档时同步中英两份。然后按改动范围验证。主机测试命令为：

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py'
git diff --check
```

纯文档改动只需检查链接和发布内容，无需重建模拟器。修改 QEMU 补丁后，要使用新的 `HARMATTAN_PORT_WORKSPACE`，从干净源码应用全部补丁、重新构建，并执行相关客体诊断，见[构建说明](building.zh-CN.md)。只修改解包后的 QEMU 树不会更新维护中的补丁。

用 `git add <文件>...` 明确暂存已审阅的文件，然后执行：

```sh
python3 scripts/check-public-tree.py
git diff --cached --check
git diff --cached --stat
git diff --cached
```

发布检查针对 Git 已跟踪或索引列出的路径，读取当前工作区内容。因此新文件应先暂存再检查，已暂存版本也应与受检工作区保持一致。这个检查不能代替审阅暂存区差异。

提交后推送功能分支，并向 `main` 发起 Pull Request。合并前确认 CI 通过，并附相关本地运行证据；合并后用 `git pull --ff-only` 更新本地 `main`。这是建议采用的审阅流程，不表示仓库已配置分支保护。

## 构建、输入与备份

- 原始下载物和准备好的客体基础盘，与一次性运行目录分开保留。基础主盘尚不能仅凭公开仓库端到端重建，所以 GitHub 不是完整运行环境的备份。
- 正常原生启动器使用每次运行独立的克隆和快照，Notes 等会话内修改在退出后丢弃。历史启动脚本可能不同，应使用构建说明中的原生入口。
- 删除旧运行目录前，先保存需要的测试证据，并确认没有活动 QEMU 进程使用该目录。不要整体清空 `extracted/`，其中还包含客体输入和图形依赖。
- 机器专用路径通过 shell 环境设置保留。输入导入器用于初次准备，会拒绝覆盖现有目标，不是持续同步目录的工具。

## 以后迁移目录

当前放在 `publish/` 下可以继续使用。长期也可将研究目录与公开源码目录放为同级，方便导航；但现有构建树引用了绝对 DGLES/Homebrew 动态库路径，直接移动可能导致启动失败。应在最终位置重新建立 checkout、准备输入、重建 QEMU/DGLES 并验证启动，之后再停用旧构建。只移动 `.app` 不够。

独立的[预编译发行版](releases.zh-CN.md)包含运行依赖，可以直接移动应用目录，无需重新编译。其导入输入保存在 Application Support，与源码工程分开。上述源码构建路径仍依赖选定的构建位置。
