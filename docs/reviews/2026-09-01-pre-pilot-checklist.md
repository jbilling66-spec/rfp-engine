# Pre-pilot checklist — suggested next steps (2026-09-01)

*Companion to the enterprise-readiness review
(`2026-09-01-enterprise-readiness-review.md`, which holds the full
findings register with file:line evidence). Verdict from that review: no
finding is a showstopper for the pilot as this repo defines it — one
machine, loopback, trusted operators, the answering-session handoff
seam, a pinned tag, synthetic data. This checklist is the small subset
worth landing BEFORE the pilot tag is cut, because each one bites during
a pilot specifically. Everything else in the register belongs in the
parallel refinement track and loses nothing by waiting.*

## Fix before cutting the pilot tag (~3–5 days total)

| Order | Register # | Fix | Why it bites during a pilot |
|---|---|---|---|
| 1 | P0-5 | Mid-gate crash convergence: key gate-decision replay on (decision, actor), not a byte-identical client timestamp (`engine/strategy/gate.py:148-171` + `engine/web/server.py:101`) | A crash during a gate decision bricks that pursuit — manual file surgery is the only recovery, on the flagship control, in front of colleagues |
| 2 | P0-4 | Cross-process write lock: CLI mutating commands take the same workspace flock the server holds (`server.py:64-77`; CLI takes none) | The runbook has the host running CLI steps beside a live server; today that races run minting and artifact writes |
| 3 | P0-3 | Run-id mint: `max(existing)+1` and refuse to open an existing `run.jsonl` for a new run (`engine/workspace/pursuit.py:92-96`) | One "cleanup" of a run directory silently merges two audit traces into one file |
| 4 | P0-7 | Host-header validation + basic security headers on the web app (no middleware exists in `engine/web/server.py`) | The pilot machine's browser is on the open web while serving all pursuit content unauthenticated on loopback — DNS rebinding is a real exposure, hours to fix |
| 5 | P0-2 | Verify the recorded `frozen_sha256` at every frozen-brief read; refuse writes to `*.frozen.json` outside gates (`strategy/gate.py:217` vs `drafting/draft.py:111`, `validation/validate.py:89`) | Cheap, and it makes the gate/freeze guarantee the pilot is showcasing actually true |
| 6 | P0-8 | Upload size caps + decompression limits on xlsx/docx parsing (`server.py:231, 598-612`) | A malformed buyer workbook shouldn't OOM the single server process mid-demo |

Then: `make check` green → cut the pilot tag. The work side runs the tag
read-only (standing rule 7); later fixes ship as new tags picked up
between pursuits, never mid-pursuit.

Interim mitigations if the tag must cut sooner: host never runs CLI
against the served workspace and never deletes run directories (covers
items 2–3); pilot machine browses nothing while serving (partially
covers item 4).

## Not needed for the pilot — one nuance worth knowing

P0-1 (no timeout on live API calls) is the register's worst operational
finding, but it applies to the **live API caller only**. The pilot's
answering-session lane already has a bounded wait per call with honest
refusal on timeout (`engine/llm/handoff.py`, `--handoff-timeout`). It
becomes urgent the day `RFP_LIVE=1` is ever flipped — fix it then, or
opportunistically (it is a small change).

## Preconditions that activate only when REAL data enters (the A1 call)

The pilot is unconditionally green on synthetic pursuits. Admitting a
real public solicitation is the owner's A1 decision, and three register
items become preconditions rather than parallel work:

1. **Feed the tripwire first** — `tripwire-local/tokens.txt` with the
   firm's and clients' restricted names, delete the committed empty-list
   attestation — BEFORE the first restricted name exists anywhere
   (README, "Make it yours" step 1).
2. **P1-2** — at minimum full-disk encryption on the pilot machine plus
   a written retention note; every artifact, log, and provenance file is
   plaintext.
3. **P1-9** — a retention decision for `pending-calls/`: in handoff
   mode every judgment prompt, client text included, persists on disk
   indefinitely by design (it is the audit record). Fine for synthetic;
   a policy decision for real material.

## Why piloting now also advances the register

Edit-survival, reviewer-effort, and gate-wait instrumentation are
already wired; the unmeasured quality lanes (drafter rubric, judge
calibration — register P2-9) need exactly the human-reviewed sessions a
pilot produces. Running the pilot collects the evidence the eval program
is waiting on.
