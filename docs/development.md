# Local development workflow

[简体中文](development.zh-CN.md) · [Building](building.md) · [Contributing](../CONTRIBUTING.md)

Use your checkout of `YZune/harmattan-qemu` as the maintained home of QEMU patches, helpers, tests, and public documentation. Open that repository root in your editor or Codex when working on the emulator.

## Repository and local data

| Location | Purpose | Version control |
| --- | --- | --- |
| `ports/`, `scripts/` | Maintained patches, compatibility helpers, build and test tools | Commit reviewed changes here |
| `docs/`, root documentation, `.github/` | Bilingual documentation, reviewed captures, CI and contribution templates | Commit changes here |
| `downloads/` | Local source archives and user-supplied historical inputs | Ignored; back up separately where needed |
| `extracted/` | Unpacked trees, builds, prepared guest inputs and run artifacts | Ignored; some inputs are not currently reconstructible automatically |
| A separate Harmattan research repository | Source archaeology, browser prototype, historical evidence and experiments | Independent local history; not automatically synchronized |

The public repository was exported with fresh Git history. If it lives inside a research repository under `publish/harmattan-qemu`, it is still an independent repository: neither a submodule nor a worktree. Changes in the parent's old `scripts/` or `ports/` do not reach GitHub. Treat those copies as historical references; develop future emulator changes in this checkout. Review and transfer any later research fix individually, retaining its provenance. Do not merge unrelated histories merely to synchronize the directories.

The parent repository can locally exclude `/publish/` through its `.git/info/exclude` to avoid accidentally staging the nested repository. Run Git commands from the intended repository root and inspect `git status` first.

## A normal change

Start from a clean worktree. Replace the example branch name with the change you are making:

```sh
git status --short --branch
git switch main
git pull --ff-only
git switch -c codex/example-fix
```

Edit the maintained source or patch files and update both language editions when documentation changes. Then run the checks relevant to the change. The host suite is:

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py'
git diff --check
```

For a documentation-only change, verify links and publication contents without rebuilding the emulator. For a QEMU patch change, use a fresh `HARMATTAN_PORT_WORKSPACE`, apply the full patch sequence, rebuild and run the affected guest diagnostics; see [Building](building.md). Editing only an unpacked QEMU tree does not update the maintained patches.

Stage the exact reviewed files with `git add <file>...`. Then run:

```sh
python3 scripts/check-public-tree.py
git diff --cached --check
git diff --cached --stat
git diff --cached
```

The publication check examines tracked/index-listed paths using their current worktree contents. Stage new files before running it, and keep those staged files consistent with the checked worktree. It does not replace reviewing the staged diff.

Commit, push the feature branch, and open a pull request to `main`. Require a successful CI run and the relevant local runtime evidence before merging. After merging, update local `main` with `git pull --ff-only`. This describes the recommended review workflow; it does not claim that branch protection is configured.

## Builds, inputs, and backups

- Preserve original downloads and prepared base guest disks separately from disposable run directories. The prepared main disk cannot yet be regenerated end-to-end from the public repository, so GitHub is not a backup of the complete runtime environment.
- The normal native launcher uses per-run clones and snapshots. Notes edits in those sessions are discarded on exit. Historical launch scripts can behave differently; follow the native entry point in the build guide.
- Before removing an old run, retain any needed test results and check that no active QEMU process uses it. Do not run a blanket cleanup over `extracted/`: it also contains guest inputs and graphics dependencies.
- Keep machine-specific paths in shell environment settings. The input importer is for initial preparation, refuses existing destinations, and is not a continuous directory-sync tool.

## Moving the checkout later

Keeping the checkout under `publish/` is currently usable. A sibling research directory and public source directory can be easier to navigate long term, but moving the current build tree can break its absolute DGLES/Homebrew library references. Recreate the checkout, supply its inputs, rebuild QEMU/DGLES at the final paths, and verify startup before retiring the old build. Moving a `.app` alone is not sufficient.
