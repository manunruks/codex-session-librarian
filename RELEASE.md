# Release operation

Release candidate: **0.1.0**. Publisher: an upstream maintainer with permission to
`warevista/codex-session-librarian`. Manunruks prepares and verifies the candidate;
read-only upstream access does not authorize impersonating the repository owner.

1. Review/merge the release PR after its four core/media CI jobs pass. Verify the
   selected upstream commit includes LICENSE, version, secret review and demo.
2. From that exact commit, verify `./csl --version`, run the isolated synthetic
   demo and review the recorded native/live evidence. Do not call a skipped test
   a pass or pay to repeat inference without a reason.
3. Publish GitHub Release `v0.1.0`, targeting the verified commit, with notes from
   CHANGELOG.md. No personal session bundles or private test outputs are assets.
4. Check a clean installation from that tag. Update the changelog's publication
   status and the landing's release/install links to match what is available.

No package-registry publication, repository transfer or extra infrastructure is
required for this Git-based initial release. A later package/channel needs its own
scope and verification.
