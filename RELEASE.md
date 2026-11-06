# Release operation and published state

## Published v0.1.0

[GitHub Release v0.1.0](https://github.com/vitral-ai/codex-session-librarian/releases/tag/v0.1.0)
was published November 5, 2026 from exact commit
`edd05bb20eb145dea6178d548f1363b9516102af`.
The validation record for its runtime contains 253 tests, isolated installation
and an offline demo. Repository transfer to Vitral preserved this tag and release.
Do not move the tag or edit its contents to include later development changes.

The issue #7 display correction and additional secret-review checks are on main,
**Unreleased**, not in v0.1.0. The 260-test validation in
[TOOL_DISPLAY_VALIDATION.md](docs/TOOL_DISPLAY_VALIDATION.md) belongs to that later
code. Native display, structural fidelity and model continuation are separate
measurements. No 0.1.1 publication follows automatically from an audit closing.

## Procedure for a future authorized release

1. Obtain a scoped release decision. Select and record the exact upstream SHA;
   never substitute a moving main. Review license, version, changelog and scope.
2. Verify regressions, isolated installation and synthetic demo at that SHA.
   Do not count skipped tests as passes or attribute a prior run to another commit.
3. Verify the proposed tag does not already exist. Publish only the selected SHA
   and reviewed notes; never overwrite or retag an existing version. No private
   histories or test credentials may be release assets.
4. Install from the published tag in a fresh isolated environment. Check version,
   resolved SHA and demo. Align README, web and user documentation with reality.

Use the operator's own authorized GitHub identity (Manunruks uses gh-manunruks).
Repository access does not itself authorize a new version, a transfer or scope
expansion. Package-registry publication requires its own plan and verification.

## Native evidence gate

Ordinary CI covers Python 3.11/3.13 and optional media in process mode; it does not
by itself establish native CLI loading or migration E2E. The manual isolated native
workflow pins Codex 0.166.0 and Claude Code 2.1.308, enables native/migration opt-ins
and requires bubblewrap for media. Use synthetic temporary homes, no personal
credentials and no model inference. Record actual results, not workflow existence.
Paid continuations are a separate explicitly authorized stage.
