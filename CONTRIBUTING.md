# Contributing

[简体中文](CONTRIBUTING.zh-CN.md) · [Roadmap](docs/roadmap.md) · [Local workflow](docs/development.md)

Contributions in English or Chinese are welcome. You do not need a firmware image to improve host tests, documentation, build scripts, or device-model source.

## Before changing code

Read the [architecture](docs/architecture.md) and [status](docs/status.md). Choose a bounded problem. For substantial graphics or board changes, describe the intended behavior in an issue first so implementation and review can stay focused.

## Development and validation

```sh
python3 -B -m unittest discover -s scripts/harmattan-qemu/tests -p 'test_*.py'
python3 scripts/check-public-tree.py
git diff --check
```

Keep source changes in the maintained patch files; extracted QEMU trees are build outputs. Use a fresh `HARMATTAN_PORT_WORKSPACE` to validate a changed patch stack. Do not assume that an incremental build proves a clean application of patches.

For guest-visible changes, include the exact launcher command, host/guest versions, input identifiers, positive and relevant negative results, and a concise diagnostic summary. State separately whether you tested host logic, a headless guest, a Cocoa window, or actual mouse interaction. RAM frame sampling does not measure display FPS.

Do not weaken a validator merely to make a run pass. Explain any changed expectation and retain checks for unknown GPU faults, lifecycle errors, and failed guest commands. Preserve original UI behavior where feasible; use explicit compatibility helpers instead of silently replacing product artwork or inventing system data.

## Pull requests

- Explain the concrete problem and resulting behavior.
- Keep scope small enough to reproduce and review.
- Update both language editions when documentation changes. If translation needs help, say so in the PR.
- Preserve inherited copyright and license notices. Identify the source of imported code.
- Include validation and remaining limitations.
- Submit source, documentation, and reviewed minimal diagnostics. Runtime screenshots need capture provenance and visual review; the publication check permits only the explicitly listed captures. Never upload firmware, SDK packages, personal guest databases, credentials, full memory dumps, or private paths.

By submitting code, you confirm you have the right to contribute it under the applicable file license. A separate contributor agreement is not required by this project.

CI runs host tests and the public-tree check. It does not fetch proprietary inputs or claim full guest compatibility. AppKit tests are skipped on Linux; macOS exercises them.
