# Contributing

## How this repository works

This repository is a **published mirror**. Development happens in a
private canonical repository, and each release is exported here by a
scrubbing tool that verifies the tree — allowlisted paths only, a
residue scan, and the full test suite green — before anything is
committed. The public history therefore moves in release-sized steps,
not day-to-day commits.

That shape sets what contributions can land where:

- **Issues: yes, please.** Bug reports, confusing docs, portability
  findings, design questions — all welcome. An issue is the fastest way
  to change this codebase, because it travels to the canonical repo and
  comes back fixed in a release.
- **Pull requests: usually not mergeable directly.** A PR here cannot
  merge into history that is generated elsewhere. Small, clearly-scoped
  patches may be re-applied on the canonical side with credit in the
  release commit; for anything larger, open an issue first so the work
  happens where it can actually land.
- **Forks: encouraged.** The engine is built to be cloned and tailored —
  see the README's "make it yours" steps. A fork owns its own history,
  records, and token list from day one.

## Ground rules for any contribution

- **Synthetic data only.** No real client names, documents, fees, or
  people in any fixture, test, issue, or example — invented stand-ins
  only. This is the repo's founding rule and the tripwire enforces it.
- **Describe restricted strings, never paste them** — in code, tests,
  issues, and commit messages alike. If you are reporting that a string
  appears where it shouldn't, say what kind of string and where; do not
  reproduce it. Security-sensitive findings go through
  [SECURITY.md](SECURITY.md), not the issue tracker.
- **Never weaken a test to make it pass.** A red suite is a finding.
  Fixtures and mocks are never presented as live proof.

## Building and testing

The README's quick start is the whole setup: create the uv venv,
install from the lock, run `make check`. The suite is offline and
spends nothing; it must be green before and after any change you
propose. `make check` is also exactly what CI runs.
