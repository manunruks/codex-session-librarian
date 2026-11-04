# Contributing

CSL is a Vitral project licensed under Apache-2.0. Contributions submitted for
inclusion are made under that license; preserve third-party notices and identify
any material you did not write. No additional contributor agreement is required.

Before changing behavior, read `AGENTS.md`, the provider matrix and the relevant
transfer/conversion contract. Describe a reproducible problem and keep changes
focused. Add synthetic regression coverage, update the capability matrix when
scope changes, and document the versions actually checked.

```sh
python3 -m unittest discover -s tests -v
```

Keep homes isolated for native checks. Never attach real conversation exports,
credentials or personal history to an issue/PR. Do not run paid inference without
explicit authorization and a bounded test configuration. Read
`docs/LIVE_VERIFICATION.md` before proposing live compatibility claims.

Open a pull request with the problem, resulting behavior, tests and limitations.
Maintainer review is required before integration. Avoid broad rewrites, silent
loss of historical content and automatic permission/sandbox bypasses.
