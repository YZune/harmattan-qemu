# Community roadmap

[简体中文](roadmap.zh-CN.md)

These are proposed contribution areas, not promised release dates. Start with a focused issue and link the resulting evidence.

| Priority | Work | Completion condition |
| --- | --- | --- |
| 1 | Independent setup reproduction | Another contributor builds from a fresh checkout and records host/tool versions, missing steps, and results |
| 1 | Guest preparation pipeline | A deterministic, documented process accepts user-provided original inputs, validates identities, creates only derived files, and reaches the normal diagnostic entry |
| 1 | Application compatibility reports | One original application has reproducible launch, interaction, exit and relevant pixel/identity checks |
| 1 | macOS packaging and independent distribution verification | A built app relocates between directories without dependency-loading failures; all bundled libraries have source/license provenance |
| 2 | Linux host investigation | A documented build/display strategy plus a bounded board or rendering result; portable host-test success alone is insufficient |
| 2 | GLES correctness | A missing or incorrect call has a minimal guest reproducer, explicit memory/lifecycle checks, and a positive/negative regression |
| 2 | Device model accuracy | A bounded reset, interrupt, clock or storage behavior is tied to source/documentation and tested without breaking the default guest |
| 3 | Broader UX verification | A defined keyboard language, orientation or long session has repeatable evidence and stated limits |
| Ongoing | Bilingual documentation | Both editions explain the same supported path and pass the local-link check |

Good first contributions: improve an error message with a real failed setup, clarify an input's provenance, fix a translation, or submit a sanitized compatibility report. Deep graphics and device work needs narrower proposals and stronger validation, not a larger initial PR.

A redistributable guest image is a separate effort: every included component needs a known source and permission basis. This project does not promise to host retail firmware as a shortcut.
