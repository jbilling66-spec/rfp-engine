# AGENTS.md

Agent tooling working in this repository: read [CLAUDE.md](CLAUDE.md) —
the session protocol and standing rules (data boundaries, zero-spend
default, deferral discipline) — and follow it as law. The code rules in
[spec/CLAUDE.md](spec/CLAUDE.md) apply to every line of code.

Orientation: [docs/graph/doors.md](docs/graph/doors.md) indexes every
entry point (web routes, make targets, CLI); [docs/graph/modules.md](docs/graph/modules.md)
maps the packages. `make check` is the offline gate and must be green
before and after your change; docs under docs/graph/ and docs/pilot/ are
machine-pinned to the code, so doc and code move together.
