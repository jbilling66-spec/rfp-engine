# Security policy

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability). Reports filed there reach the
maintainers without becoming public. Please do not open a regular issue
for anything security-sensitive — issues are public from the moment they
exist.

What helps: the affected file or subsystem, a reproduction (synthetic
input only), and the impact as you understand it. You will get an
acknowledgement in the report thread, and a fix lands in a release —
see [CONTRIBUTING.md](CONTRIBUTING.md) for how releases reach this
repository.

## Two rules for reports

- **Synthetic data only.** Never include real client names, documents,
  fees, or people in a report — not even as the example that triggered
  your finding. Reproduce it with invented stand-ins; the engine's own
  test fixtures show the pattern.
- **Describe restricted strings, never paste them.** If your finding is
  about a leak — a name that survives a scan, a token that reaches a
  file it shouldn't — describe the string's class and where it appears.
  A report that pastes the leaked value is itself the leak.

## Supported versions

The latest tagged release. Older tags are not patched — update to the
newest tag and re-test before reporting.

## What this engine already enforces

The test suite carries the security posture: a tripwire against
restricted tokens (`tests/tripwire/` — public clones ship a committed
attestation of the empty-list posture), zero network access from the suite, and
zero-spend-by-default model calls. A clone that weakens those tests has
left the supported configuration.

One posture to know before real data: the command-line tools take an
`--actor` name that is declared, not authenticated. Authorization for
destructive operations (purge) is checked against that declared name, so
shell access to the host is the actual trust boundary until the SSO seam
reaches the CLI (a planned phase, tracked in the maintainers' roadmap).
