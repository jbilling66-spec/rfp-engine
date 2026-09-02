# RFP Response Engine v2

A drafting workbench for RFP responses, built for consulting firms: feed it
an RFP package, it reads the package, researches against your firm's
knowledge base, and drafts a response — stopping for a human decision at
every gate. It never sends anything to a buyer; it is an internal drafting
assistant with mandatory human review at the boundary. Flavored for ERP
implementation consulting; the service line lives in config, not code.

Three properties are structural, not aspirational, and each is enforced by
a named test:

- **Zero spend by default.** The suite and every default code path use a
  fake model caller. Live calls require `RFP_LIVE=1`, an API key, and a
  priced model table, and run behind cost ceilings — the live caller
  refuses construction without all three.
- **Restricted names cannot land in the repo.** A tripwire scans every
  tracked file, every extracted binary, all git history, and commit
  metadata against your organization's restricted-token list (see
  *Make it yours*).
- **Docs cannot rot.** The architecture docs under [docs/graph/](docs/graph/)
  are compared against the code in both directions — a doc row with no code
  twin is a test failure, and so is code with no doc row.

## Quick start (offline, ~5 minutes)

Requires Python 3.11, [uv](https://docs.astral.sh/uv/), git, and a POSIX
platform (macOS or Linux; the Makefile assumes `.venv/bin/python`).

```
uv venv --python 3.11 .venv
uv pip install --require-hashes -r requirements.lock
uv pip install --no-deps -e .
make check
```

`make check` runs the full offline suite — no Docker, no model weights, no
network, no spend. The tripwire (the committed leak scanner) needs a
restricted-token posture before it passes: a public clone ships with the
explicit empty-list attestation (`tests/tripwire/ATTESTATION.md`)
committed, so the suite is green immediately; a checkout with neither
that attestation nor a `tripwire-local/tokens.txt` stops with
instructions. That refusal is the intended signal, not a bug.

The environment is pinned exactly: one test asserts the venv matches
`requirements.lock` in both directions (every pin at its version, nothing
extra installed). If your platform or index cannot satisfy a pin, that
test fails honestly — resolve deliberately (and re-lock with `make lock`),
never by weakening the check.

## The two tiers: tests-green vs. actually-usable

`make check` green does **not** mean the engine can read a real PDF. Rich
document extraction runs in a Docker container with vendored model
weights:

```
make gate-image          # builds the extraction container (~GB-scale)
make extraction-models   # downloads weights (the one deliberately-online step)
make weights-verify      # digests must match the committed manifest
```

Give the Docker VM ≥16 GB of memory. Until then, PDF/DOCX intake either
refuses loudly or (with `RFP_EXTRACTION_FALLBACK=1`) runs legacy
extractors with every result stamped `degraded`. Plan roughly an hour for
the full setup; [docs/steward/maintenance-guide.md](docs/steward/maintenance-guide.md)
is the operational manual.

## Running it

```
.venv/bin/python -m engine serve --workspace pursuits/web
```

The workbench binds `127.0.0.1:8400` — localhost only, by design; putting
it behind a reverse proxy is your deployment decision. Open the app,
declare an operator name, create a pursuit, upload an RFP workbook, press
**Advance**. The operator-facing walkthrough is
[docs/pilot/operator-guide.md](docs/pilot/operator-guide.md); the pilot
runbook and the Claude Code answering-session contract (for running
judgment steps through an operator seat instead of an API key) are beside
it in [docs/pilot/](docs/pilot/).

## Where everything is

- [docs/graph/doors.md](docs/graph/doors.md) — **start here**: every entry
  point (web routes, make targets, CLI commands), machine-verified.
- [docs/graph/modules.md](docs/graph/modules.md) /
  [docs/graph/artifact-flow.md](docs/graph/artifact-flow.md) — the code
  map and the artifact pipeline.
- [docs/steward/](docs/steward/) — operations: machine setup, daily
  commands, knowledge-base stewardship.
- [docs/advisor/](docs/advisor/) — the end-user help surfaced inside the
  web UI.
- [spec/CLAUDE.md](spec/CLAUDE.md) — the standing code rules;
  [CLAUDE.md](CLAUDE.md) — session law for agentic coding sessions
  (Claude Code reads it automatically).

## Make it yours

The engine ships configured for a synthetic firm. To tailor it:

1. **Restricted-token list** — create `tripwire-local/tokens.txt` (one
   token per line) naming your clients' and firm's restricted names, and
   delete the committed `tests/tripwire/ATTESTATION.md` (the empty-list
   posture a public clone ships with). Do this BEFORE the first
   restricted name exists anywhere. This is your leak tripwire; feed it.
2. **`config/`** — `models.yaml` (model ids + prices — verify against the
   current price sheet before any live run), `rates.yaml` (placeholder
   hourly costs, labeled synthetic), `voice-spec.md` (your writing
   standard), `kb-access.yaml` (who may touch client-identifying
   provenance), `manifests/` (service-line obligations),
   `templates/firm-default-template.docx` (swap in your firm's template —
   note the byte pin in `tests/fixtures/test_docx_twins.py`).
3. **Seed the knowledge base** — the committed corpus under [kb/](kb/) is
   wholly synthetic (see [kb/README.md](kb/README.md)); the `kb seed` and
   ingestion doors in doors.md are the path to your own.
4. **Prompts** — [prompts/](prompts/) holds one directory per agent; some
   are fingerprint-locked to eval baselines, and the failing test names
   the regeneration step when you edit one.

## Notes for adopters

- Code and records cite `B-numbers` (B29, B85, …) — an internal decision
  register that is not part of this repository. Treat them as provenance
  markers, not links.
- Windows is unsupported (POSIX file locking, `.venv/bin` layout).
- CI runs the documented bootstrap on ubuntu and macOS
  (`.github/workflows/check.yml`).

## Contributing and security

Issues are open and welcome — bug reports, portability findings, design
questions. [CONTRIBUTING.md](CONTRIBUTING.md) explains how changes land
(this is a published mirror of a private canonical repository, so fixes
arrive in release-sized steps), and [SECURITY.md](SECURITY.md) is the
route for anything security-sensitive — never a public issue.

## License

Apache-2.0 — see [LICENSE](LICENSE).
