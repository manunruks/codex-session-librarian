# Isolated Migration Validation

The migration wrapper is tested at two levels: focused unit/native regressions
in `tests/test_migration.py`, and real command-line migrations between isolated
environments in `tests/test_migration_e2e.py`. All conversation fixtures and
credentials-like strings are synthetic.

Recorded result on 2026-11-04: **223 tests passed**, including all 12 isolated
migration subprocess cases and 14 focused migration tests; no tests skipped in
the full opt-in run. Runtime: 102.224 seconds. The existing optional media/native
regressions were enabled alongside the new migration cases.

## Environment

- Linux; installed Codex CLI 0.166.0; Python 3.14.8 for the recorded run.
- Two separate Python virtual environments, created without pip/dependencies.
- Distinct old/new `HOME`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, projects and temp dirs.
- Actual CSL subprocesses and native Codex metadata listing, history reading and
  archiving. No model turn is requested and historical tool records never execute.
- Bubblewrap removes external networking, mounts the host read-only and permits
  writes only inside the synthetic lab. Real account credentials are not passed
  in the subprocess environments. No personal histories can be modified there.
- A filesystem-backed `gh` stand-in implements repository checks, immutable
  releases, asset upload/download and API metadata, with deliberate faults.
  No real GitHub releases or team-inbox entries are created.

These are separate local environments, not separate physical PCs or hardware
VMs. The GitHub transport is simulated: this does not prove live credentials,
permissions, rate limits or service availability on a teammate's machine.

## Scenarios

| Scenario | Assertions |
| --- | --- |
| 125-session migration | All selected UUIDs uploaded/restored; new identities; source unchanged until explicit cleanup |
| Three-page cold listing, 257 sessions | No sessions lost when creation timestamps are identical; both interactive sources/providers included |
| Visibility | Archives and exec/agent sessions excluded; restored sessions visible in the native listing |
| Content | Distinct user/assistant/tool facts, Unicode, titles and destination cwd retained; native loader reads restored answer |
| Repeat download | Identical local UUIDs reused; no duplicate imports |
| Interrupted upload | Separate process resumes completed work without republishing successful shares |
| Interrupted/corrupt download | Bad session not installed; earlier successes retained and reused on retry |
| Wrong destination cwd | Existing imports unchanged; retry in the original directory works |
| Invalid index | Malformed JSON and cross-repository index rejected before restore |
| Permission failures | Public repository and read-only access block upload |
| Lost index publish response | Identical published index accepted after confirmation; no duplicate index |
| Conflicting index | Different remote content never overwritten or accepted as completion |
| Secret review | Non-interactive detected secret blocks upload; explicit scrub changes only exported copy |
| Portable/raw | Existing export stripping/preservation semantics remain intact |
| Cleanup | Preview changes nothing; explicit confirmation archives, never deletes; archived bytes match originals |
| Cleanup guards | Changed original blocks all cleanup; destination machine cannot clean source without its upload state |

The focused tests additionally reject unsafe RPC methods (including model turns
and deletion), repeated listing cursors, duplicate index entries, invalid share
IDs and changed sources before completing a resumed upload.

## Findings Corrected

The larger subprocess runs exposed behavior not caught by two-session tests:

1. The installed Codex default creation-time pagination cursor omitted records
   sharing the boundary timestamp. Migration now explicitly uses the native
   `recency_at` cursor with a UUID tie-breaker. The 125/257 fixtures deliberately
   retain identical creation timestamps to guard against regression.
2. A successfully published index followed by a lost response left a retry stuck
   at "release already exists". Publication now verifies identical remote bytes
   before recording success and refuses conflicting indexes.

Individual share-upload response ambiguity remains subject to the underlying
share command's documented limitations. Cleanup confirmation remains a human
verification, not automatic proof of successful inference on the destination.

## Reproduction

Standard focused suite, no optional native binary required:

```bash
python3 -m unittest discover -s tests -p test_migration.py -v
```

Full subprocess migration suite requires Codex and working Linux bubblewrap:

```bash
CSL_RUN_MIGRATION_E2E_TESTS=1 python3 -m unittest discover -s tests -p test_migration_e2e.py -v
```

Combine with existing optional decoder/native checks after installing the
documented media test dependencies:

```bash
CSL_RUN_MIGRATION_E2E_TESTS=1 CSL_RUN_MEDIA_TESTS=1 CSL_MEDIA_SANDBOX=required \
CSL_RUN_CODEX_NATIVE_TESTS=1 CSL_RUN_CLAUDE_NATIVE_TESTS=1 \
~/.local/share/csl/media-venv/bin/python -m unittest discover -s tests -q
```

Tests clean up their synthetic homes/exchange automatically. Nothing in these
commands publishes to GitHub, copies a personal login, or buys inference.
