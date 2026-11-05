# Changelog

## Unreleased

- Refresh Codex's native resume-picker metadata after import/receive and once per
  migration restore attempt. Add `csl index --native` for already-imported sessions
  that open by UUID but are absent from a running picker's database-only view.
  No history rewrite, UUID changes, direct native DB edits or inference.

- Explicit `--repair-legacy-compaction` recovery for old Codex portable copies
  with one orphaned final summary annotation. Pending migration exports can
  recover without resending completed shares; source files and readable turns
  remain intact, and missing hidden context is explicitly labeled.

- Codex batch migration: `migrate upload`, `download` and confirmation-gated
  archival cleanup, reusing the existing private share/receive exchange.
- Resumable uploads, idempotent downloads and source checksum guards; normal
  interactive sessions are selected without including archives or agent forks.
- Stable recency pagination prevents timestamp-tied sessions being skipped;
  identical already-published migration indexes recover from lost responses.
- Added 12 isolated subprocess migration scenarios, including 125-session
  restore/cleanup and a cold 257-session listing. See
  [migration validation](docs/MIGRATION_VALIDATION.md).

## 0.1.0 — Initial licensed release

Prepared 2026-11-02. Publication and tag are pending until the release commit is
merged and the corresponding GitHub Release exists. This file is not proof of
publication. Native transcript formats and cross-CLI conversion remain experimental.

### Included

- Apache-2.0 license with Vitral attribution and a distinct CLI `--version`.
- Codex local library: lexical search, evidence-oriented recall, inspection,
  native working forks and archived clones.
- Native Codex and Claude Code ZIP/private-exchange handoffs. Imports create new
  local identities; credentials, project files and installed tools are not copied.
- Explicit canonical-v2 conversion of supported text, completed tools, references,
  embedded images and PDFs. Optional media decoding stays outside the core CLI.
- Local export/share secret review: keep, scrub or cancel for each detected value;
  `--allow-secrets` and `--scrub-secrets` are explicit non-interactive alternatives.
  Scrub edits the output copy, preserving source files and rebuilding checksums.
- Fixed loss of assistant tool-call phase in Claude/canonical → Codex → Claude.
- Reproducible synthetic demo and recorded bounded live validation.

### Verification and limits

See [compatibility evidence](docs/COMPATIBILITY_VALIDATION.md),
[demo](demo/README.md) and the [provider matrix](docs/PROVIDER_MATRIX.md).
Do not infer universal context recovery, compatibility with future CLI versions,
Claude library/search parity, or safe-to-share status from a successful transfer.
Secret scanning is partial and does not redact opaque/binary attachments.

The release regression suite runs in CI on Python 3.11 and 3.13, with separate
core/media jobs. Native localhost loader checks and explicitly paid synthetic
continuations provide separate evidence; CI alone does not establish live recall.
