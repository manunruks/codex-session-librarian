# Release operation

Prepared version: **0.1.0**. Publication status is recorded in
[GitHub Releases](https://github.com/warevista/codex-session-librarian/releases);
this preparation document does not establish that a tag or Release exists. PR #6 is merged at
`4c7dee029a4525491307030998b79baa0b25a7e0`, including migration, picker discovery
and focused audit fixes. The five runtime modules match the reviewed corrections;
253 tests, isolated installation and offline demo passed on this upstream commit.
Publisher: an upstream maintainer with permission to
`warevista/codex-session-librarian`. Manunruks prepares and verifies the candidate;
read-only upstream access does not authorize impersonating the repository owner.

1. Select and record the exact upstream SHA to publish; do not silently use a later
   main. PR #6 is already merged. Verify the selected commit's CI and that it includes
   LICENSE, version, secret review, migration
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

The P2 investigation of visible tool events in Codex does not automatically block
0.1.0. Model recall and visible-history representation are different measurements.
If a different publication SHA changes runtime behavior, rerun its regressions
before release. For documentation-only descendants, record unchanged runtime
fingerprints and the descendant's actual CI result; do not pretend a prior run
was executed at a different SHA.
