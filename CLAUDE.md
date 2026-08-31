# CLAUDE.md — RFP Engine v2 build sessions

*Read this every session. The spec's standing rules (spec/CLAUDE.md) apply to every line of code; this file adds the session protocol and the pre-production rules.*

## What this is

**This is the production system.** Not a prototype, not a throwaway, not a pilot that gets rewritten — the code in this repo is the code that will handle confidential client material and produce documents that go to real buyers under the firm's name. Build it that way (B29).

The spec always assumed this: it never uses the word "POC," and `spec/CLAUDE.md` rule 2 exists precisely to stop a builder from simplifying away controls whose failure modes are "one client's details appearing in another's response ends the program." Earlier working files framed the current stage as a POC; that framing is retired. What remains true is narrower and still binding: **we are pre-production** — synthetic data only, zero live spend — until the A1 real-data gate opens.

The practical test: when a shortcut is tempting, the question is never "is this good enough for a POC?" It is "would I defend this once it is holding a real client's material?" A deferral is legitimate only when it is written down with the phase that closes it (CLAUDE.md rule 5).

## Authority (B30 — who wins where)

- This file owns the session protocol and the standing rules below. `spec/CLAUDE.md`'s six code rules are **live law** for every line of code — the one live exception to B2's spec-is-record posture (the B11 live-copy-vs-record pattern, applied to rules).
- ROADMAP.md's P-series owns sequencing; the spec's WP-series is design history that the phase rows map onto.
- Cite rules with their file — "spec rule N" or "CLAUDE.md rule N", never a bare "rule N": every numeral exists in both files.
- Work-rule corrections live in `lessons.md` (one screen); product decisions in DECISIONS.md. Never two homes for the same rule.

## Session protocol

*The four working records this protocol names — SESSION.md, ROADMAP.md, DECISIONS.md, lessons.md — live in the private canonical repository and do not ship in the public mirror. A fork that lacks them creates its own at first session start: the protocol is the law; the records are yours to grow.*

**Start:** read SESSION.md → lessons.md → the current-phase row in ROADMAP.md → the spec files that phase names. Then run `make check` and reconcile the result against SESSION.md's claimed state BEFORE writing any code — divergence means the last session ended dirty; fix the record first.

**During:** small commits, `[Pn]` phase prefix. Any decision or spec deviation gets a DECISIONS.md append in the same commit. Schema changes ship in their own commit (spec rule 4).

**End (or nearing compaction):** overwrite SESSION.md (snapshot · done · ordered next actions with the first written as an executable resume instruction · open questions · known-broken), flip a ROADMAP status only if its named acceptance command passed this session, commit state files together with the code.

Nothing needed to resume may exist only in conversation context. SESSION.md + ROADMAP.md + git log + the test suite are the complete state.

## Standing rules

1. **Synthetic data only, until A1.** No real client names, fees, people, or documents anywhere — fixtures, tests, prompts, sample data. The tripwire enforces the restricted-token list, which lives in the gitignored `tripwire-local/tokens.txt` — machine state, never tracked (B85 D3); extend that file whenever a new real-world token becomes a risk, and expect a loud suite failure (never a silent pass) if it goes missing. This is a pre-production gate, not a permanent property: A1 opens it under the anonymization controls. **One carved exception (B71, the owner's knowing approval 2026-08-28): PUBLIC solicitation documents and the firm's own template may sit in the gitignored pens `fixtures-local/prospect/` and `fixtures-local/firm/`, under NEUTRAL filenames, each file attested in its pen's `MANIFEST.md` (name → public source + retrieval date; publicness is attested, not machine-verified — B68's honest limit). The pens are holding space ONLY: nothing in them may be ingested, quoted, fixtured, tested, golden'd, or committed until A1 — the exception opens a shelf, not a door.**
2. **Zero spend by default.** FakeCaller is the default model caller; live calls require `RFP_LIVE=1` and go through the cost-ceiling wrapper (the live caller, `engine/llm/live.py`, refuses construction without the flag, a complete price table, and an API key — its construction gate was a P8 acceptance obligation, B30). The suite spends nothing, and CI (`.github/workflows/check.yml`) inherits the FakeCaller default. This one stays true in production — the default must never be "bills money."
3. **The bench contract is frozen:** `schemas/target-slot.schema.json` and the hosp-erp/otas-bid fixture *format* never change (spec rule 1's data-not-code exception). `fixtures-local/` stays empty until real-data approval (A1) — **except the two attested pens `prospect/` and `firm/` (rule 1's carved exception, B71); the tripwire enforces the pens' manifest + neutral-name discipline and the emptiness of everything else.**
4. **Settled decisions are settled** — synthetic-first until A1, ERP service line, separate repo, file-backed persistence *until the Azure lift* (A5), Python only. Relitigating them requires the owner, not a refactor. Note the shape of the persistence decision: file-backed is the correct choice *now* and an explicitly dated one, not a permanent architecture.
5. **Deferral is allowed; silent deferral is not — and every deferral names its closer.** "Good enough for now" is a legitimate engineering call when BOTH halves are written down: a carrier where the next person will find it (DECISIONS.md B-entry, a `TODO(spec-gap)` at the code site, or a SESSION.md known-broken line) AND the phase that closes it or the trigger that reopens it. A carrier with no phase, or a phase that survives only in someone's memory, is a defect, not a decision (merged from former rules 5+6, B30). Open: airgapped research default (B3 → A6), static voice spec (B4 → A2), headless gates (B5 → P9). The full register of pre-production deferrals and their closing phases is B29.
6. **Paraphrase, always.** Document a forbidden token by paraphrase, never by reproducing it — the file enforcing a rule is the worst place to break it. (Standing-rule home since B85 D2; the correction record that produced it stays in lessons.md, citing B47.)
7. **Read-and-run on the work side.** Every work-side copy runs at a pinned tag and no engine code is ever edited on the work side — engine changes come back to this repo and ship as a new tag (B79's law, restated here as the standing home since B85 D2; the pilot block's ROADMAP prose keeps its copy).

## Environment

- Python: `.venv/bin/python` (3.11, uv-managed: `uv venv --python 3.11 .venv` then `uv pip install -r requirements.lock -e .` — B54). Never bare `python3`.
- **New-machine bootstrap (B55, proven by the 2026-08-20 recovery):** clone → the uv venv line above → restore `tripwire-local/tokens.txt` (the restricted-token list is machine state, B85 D3 — the suite fails loudly without it) → `make check` (expect all green before anything else) → set Docker Desktop VM memory ≥16GB (`MemoryMiB` in settings — the 8GB fresh-install default OOM-kills benchmark prediction runs) → `make gate-image` → download weights via the `extraction-models` docker download step, then **`make weights-verify` against the COMMITTED manifest before any freeze** (a digest match is the continuity proof; a mismatch is a finding, never an auto-refreeze) → `make gate`. The built image and `models/` are recipe-only by decision (B55): never registry-pushed, always rebuilt from Dockerfile + extraction lock + digest manifest.
- `make check` = offline suite (zero spend) · `make slice` = M1 vertical slice (P8+) · `make eval` = eval harness (P10+) · `make public-cut` = build + verify the fresh-history public mirror (P22).
- Work-rule corrections (PIPESTATUS, suite-runtime variance, …) live in `lessons.md` — the single home (B30).
- v1 reference repo (private, the owner's): a read-only test oracle — reimplement, don't port. Absent locally (B56) but exists on GitHub — confirmed 2026-08-24 (B61). The offline suite is green without it (the salvage ledger and committed twins carry what P1 harvested), so it is not load-bearing for tests and public clones never need it; A3's head-to-head adapter pulls it at A3 kickoff (confirm remote + clean clone then).
