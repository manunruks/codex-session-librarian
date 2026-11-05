# Consolidation validation — 2026-11-05

Functional code commit: `7f281af570ae2e1b0ac22f04c00a557e8a3c430e`, based on upstream `ac5747aee265d56bee5d0f32c44cc4b16375475d`.
CLI 0.1.0 is a development candidate, not a published Release.
[PR #6](https://github.com/warevista/codex-session-librarian/pull/6) contains the changes and evidence. No new framework or remote service.

## Corrections and tests

Scoped secret scanning now includes readable business data/results and safely
serializes embedded JSON arguments. Ambiguous reserved-prefix user text is rejected
before Codex conversion writes a destination. Migration expectations bind release
metadata and package source identities. Import publishes complete native files
exclusively through private staging, preserving originals on failed copies.

253 tests passed without skips from a clean public clone, with isolated homes,
Codex 0.166.0, Claude Code 2.1.308 and required media sandboxing on Linux/Python
3.14.8. Installation and offline demo passed. Core/media CI covers Python 3.11/3.13.
[Manual native CI](https://github.com/manunruks/codex-session-librarian/actions/runs/42086700828) additionally passed 253 on hosted Linux/Python 3.11 with
a system-Python optional decoder, no model inference or personal credentials.
Two earlier native CI runs failed due to runner setup (11 failures/11 errors,
then 9 media errors); both remain visible, followed by the corrected successful run.

An independent AI reviewer exercised 15 additional adversarial checks and 11
installation/search/recall/fork/handoff commands from that public commit, preserving
the synthetic original. Four separate PNG pixel comparisons passed. These are
not human-user validation or additional methods in the 253-test suite.

## Competitive evidence

See [the reproducible benchmark](../benchmarks/consolidation/README.md), with 72
structural rows, 32 separate native checks and 16 paid continuation attempts.
CSL, Session Porter and Teleporter each passed 4/4 recall cases; sessionport passed
1/4. Failures are retained. This small corpus does not establish a population rate.
Codex thread/read acceptance is not model reconstruction; Claude's localhost
captures are separately identified. Each roundtrip result is distinct from its
first leg. Teleporter retained visible Codex tool markers absent in CSL's
representation, despite both recalling the facts correctly. It was also faster
in the bounded short-text timings. CSL preserved the tested image; unsupported
media and package operations are not scored as shared technical failures.

## Remaining boundaries

Secret detection is partial. Hashes do not establish authorship. Per-file atomicity
does not make a batch, index and receipt transactional: an interruption after
publication can leave a complete file before bookkeeping. Inspect uncertain
outcomes before retrying. Power-loss durability and every format/version/backend
are not certified. doctor structure/static fields remain narrower than full
semantic validation, real CLI loading or model recall.

No source histories, credential files or private helpers are published. Shared
artifacts are synthetic sources/outputs, sanitized logs, answers and usage. Paid
calls require explicit authorization and credentials supplied only in memory.
Publication still requires upstream merge, tag/Release and verification of that
tag. External human validation and the next product-focus decision remain pending.
