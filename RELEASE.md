# Release operation

Release candidate: **0.1.0**, not yet published. PR #1 is merged; the consolidation
candidate additionally includes migration, picker discovery and focused audit fixes.
Publisher: an upstream maintainer with permission to
`warevista/codex-session-librarian`. Manunruks prepares and verifies the candidate;
read-only upstream access does not authorize impersonating the repository owner.

1. Review/merge the consolidation PR after its core/media CI jobs pass. Verify the
   selected upstream commit includes LICENSE, version, secret review, migration
   identity checks, atomic imports and demo. Record that exact SHA in the Release.
2. From that exact commit, verify `./csl --version`, run the isolated synthetic
   demo and review the recorded native/live evidence. Do not call a skipped test
   a pass or pay to repeat inference without a reason.
3. Check that `v0.1.0` does not already exist. Publish GitHub Release `v0.1.0`,
   targeting the verified commit, with notes from
   CHANGELOG.md. No personal session bundles or private test outputs are assets.
4. Check a clean installation from that tag. Update the changelog's publication
   status and the landing's release/install links to match what is available.

No package-registry publication, repository transfer or extra infrastructure is
required for this Git-based initial release. A later package/channel needs its own
scope and verification.

## Native evidence gate

The ordinary CI jobs cover Python 3.11/3.13 and optional media in process mode.
They do not automatically prove native CLI loading or migration E2E. The manual
`Isolated native validation` workflow installs Codex 0.166.0 and Claude Code
2.1.308, enables all native/migration opt-ins and requires bubblewrap for media.
It uses synthetic temporary homes, no personal credentials and no model inference.
Record the actual run result or its blocking environment condition before release;
the presence of a workflow is not evidence that it has run successfully.
Paid continuations remain a separate, explicitly budgeted stage.
