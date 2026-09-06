# Agent instructions

[简体中文](AGENTS.zh-CN.md) · [Build guide](docs/building.md) · [Contributing](CONTRIBUTING.md)

This is the repository-wide agent entry point. `AGENTS.zh-CN.md` is its Chinese translation; keep the two aligned. Tools that do not discover `AGENTS.md` need to be explicitly pointed here. Use the user's requested scope and existing authorization for environment changes, commits, pushes, and pull requests; this file does not independently authorize publication.

## Start here

1. Work in this checkout, even when it is nested under another research repository. Inspect `git status --short --branch`, the relevant diff, `python3 --version`, and `uname -sm`. Preserve unrelated changes and local inputs.
2. Use Python 3.12 or newer for the documented commands. Select an installed interpreter first; tool selection and dependencies are in the build guide. `HARMATTAN_PYTHON` selects the interpreter used by the shell builders/launcher, not the literal `python3` commands below.
3. Read [architecture](docs/architecture.md) for patch ownership and [status](docs/status.md) for current limits. Select only the validation needed for the task:

| Task | Prerequisites and validation |
| --- | --- |
| Documentation or publication metadata | Check links/publication contents and the diff; no emulator rebuild |
| Host tools, validators, tests | Python, C compiler and Perl; run the relevant unittest cases, then the host suite for behavior changes |
| QEMU/DGLES patches | Native ARM64 macOS, required host tools and pinned source archives; fresh source build and affected graphics checks |
| Guest behavior or interactive UI | Above, plus APFS, a macOS graphics session, ARM-capable LLVM/lld, debugfs and prepared guest inputs; run affected guest diagnostics |

Linux runs portable host tests and skips AppKit tests; the complete emulator runtime currently targets Apple Silicon macOS. `check-environment.py` is a full-build prerequisite probe: its missing Mac/archive checks do not prevent source-only contribution on Linux. It checks presence/tool discovery, not hashes, guest contents, APFS behavior or compiler capabilities.

## Source-only checks

No firmware, SDK installer, guest image or device artwork is needed for these checks. macOS native tests require Xcode Command Line Tools; socket tests require local Unix-socket access.

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py' -v
git ls-files '*.sh' | while IFS= read -r script; do
    sh -n "$script" || exit 1
done
python3 scripts/check-public-tree.py
git diff --check
```

The publication check uses Git-listed paths and reads their current worktree contents. Newly added files must be explicitly staged before that check includes them. When preparing a commit, review `git diff --cached`, run `git diff --cached --check`, and keep staged and checked content consistent. In a source archive without Git metadata, the checker scans non-ignored files instead; inspect shell files directly there.

## Build and run when requested

Follow [building.md](docs/building.md) for tools and exact input layout. [inputs.json](docs/inputs.json) identifies the archives and guest files. Diagnose first with `python3 scripts/check-environment.py`, adding `--guest` when guest execution is needed. Do not change pinned versions or hashes to work around a missing/mismatched input.

For a fresh full native build, after the prerequisites are available:

```sh
mkdir -p extracted
export HARMATTAN_PORT_WORKSPACE="$(mktemp -d "$PWD/extracted/agent-qemu.XXXXXX")"
export HARMATTAN_DGLES_WORKSPACE="$HARMATTAN_PORT_WORKSPACE/dgles2-host"
export HARMATTAN_DGLES_ROOT="$HARMATTAN_DGLES_WORKSPACE/gles-libs-1.4.2/dgles2"
sh scripts/harmattan-qemu/build-dgles2-host.sh
python3 -B scripts/harmattan-qemu/smoke-dgles-host.py --workspace "$HARMATTAN_DGLES_WORKSPACE"
sh scripts/harmattan-qemu/build-arm64-port.sh --cocoa-interaction
```

Keep these exact workspace/tool selections for the following run. Agent shell calls may use separate processes: pass the same environment values again rather than assuming exports persist. The first QEMU configure may need network access for pinned Meson subprojects. If a fetch leaves partial sources, retain the failed output and use a new workspace for the retry.

With prepared guest inputs, choose the command matching the requested coverage:

```sh
# Bounded guest regression, then exit.
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-headless-diagnostic
# Bounded regression with a Cocoa window.
sh scripts/harmattan-qemu/run-arm64-ui.sh --usability-diagnostic
# Interactive session; wait for READY before input.
sh scripts/harmattan-qemu/run-arm64-ui.sh
```

Do not run all three for every task. [Get guest inputs](docs/guest-inputs.md) covers exact original media and `scripts/prepare-guest.py`; read it before preparing inputs. The script rejects mismatched original media and existing output directories, and writes only a new derived workspace. If inputs are missing, report the exact missing prerequisite and complete independent source work; never claim the guest ran. For an initial import from a user-supplied workspace, preview `scripts/import-local-inputs.py <source-workspace>` first and use `--apply` only within the authorized setup task. It refuses existing destinations and is not a sync tool.

For prebuilt distribution work, read [releases.md](docs/releases.md). `scripts/release/` owns packaging, the native first-run picker and prepared-disk import. Its private Python and prebuilt helper paths remove user-side build dependencies; they do not reconstruct retail firmware. Validate relocation, source/license completeness and the affected guest path before publishing. Use the existing user authorization; a source-only default does not prohibit an explicitly requested, reviewed binary release.

## Where to change code

- `ports/qemu-n00/`: maintained QEMU patches and skin-view source. Preserve the builder's patch order; edits only in an unpacked QEMU tree will not survive a clean build.
- `ports/dgles2/`: DGLES patch, applied to its own pinned archive rather than the QEMU tree.
- `scripts/harmattan-qemu/`: builders, launchers, scoped guest helpers, QMP controllers and `tests/`. Follow adjacent code and existing standard-library/tool patterns; retain source/ABI checks and explicit failure handling.
- `docs/`, root Markdown and `.github/`: public documentation and contribution infrastructure. Update English and Chinese together, including these instructions when commands change.

Keep original guest UI semantics and source attribution. Do not invent device telemetry or replace product behavior with mock data. Do not relax GPU, lifecycle, identity, pixel or command-failure validators merely to produce a pass; explain a changed expectation and preserve relevant negative cases.

## Local data and contribution boundaries

- `downloads/` and `extracted/` are ignored, but can contain irreplaceable inputs and active runs. Avoid blanket cleanup, history rewriting, broad process termination or staging unrelated files. Track and clean up only processes/artifacts created for the task.
- The native launcher defaults to disposable snapshots. Explicit `HARMATTAN_USER_PROFILE` selects a private persistent disk with exclusive locking and guest sync before normal exit; see [storage](docs/storage.md). Keep diagnostics on independent disks. Do not substitute the historical persistent x86/Rosetta `run-pr13-ui.sh` launcher.
- Guest overlay apply scripts write guest system directories. Never run them against the host or a physical phone. Base inputs must be quiescent before cloning.
- Keep firmware, SDK installers, disk images, fonts, standalone artwork, credentials, personal databases, memory dumps and private paths out of commits. Reviewed runtime screenshots have explicit paths/hashes in the publication checker and [capture provenance](docs/screenshots/README.md).
- Preserve inherited license notices and [NOTICE](NOTICE). Stage exact files; use the feature-branch/PR workflow in [local development](docs/development.md) when contributing. Respect authorization already given in the task without adding a separate routine approval step.

## Completion report

State what changed, which commands actually ran, their results, and what remains untested or blocked. Distinguish host tests, clean source build, native graphics execution, headless guest, Cocoa window and physical input. QMP screenshots and guest RAM sampling do not measure screen FPS. Historical records are references, not current-run evidence. Do not copy raw logs or machine-specific paths into public documentation.
