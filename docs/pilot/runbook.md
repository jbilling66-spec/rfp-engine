# The work-side runbook

*Audience: the pilot host, setting up and hosting the pilot for the firm. Every
backticked door reference in canonical form resolves to a row of the door
index — that is what the drift test checks, and no more
(`tests/contracts/test_pilot_docs.py`; docs/graph/doors.md is the index,
itself machine-compared against the code). Routes are written in template
form; CLI invocations are written in full — abbreviated forms escape the
check, so this file never uses them.*

## The posture

The pilot runs on **one work machine**. The server binds 127.0.0.1 only —
the host is deliberately not an argument until A5's reverse proxy — so
colleagues drive the web UI at that machine, not from their own. The
work-side copy is read-and-run at a pinned tag: per the pilot-block law,
"no engine code is ever edited on the work side." (The word "release" is
avoided here on purpose — in this repo it means the eval release record,
a different thing.)

Two sessions run side by side on the pilot machine: the engine's web
server in handoff mode, and a Claude Code **answering session** that
supplies the judgment steps. Operators only ever see the web UI; the
answering session is yours.

## Getting the work-side copy

```
git clone <the repo> rfp-engine-v2
cd rfp-engine-v2
git checkout <the pinned tag>   # the newest pilot tag (pilot-1 predates the generalization pass)
git describe                    # must print that same tag
```

A later pilot cut is a new tag — tags are never moved.
`git status` in this checkout stays clean for the life of the pilot; if it
is ever dirty, stop and reconcile before running anything.

## Setup

From the checkout, per the build side's bootstrap (never bare `python3`,
never `uv run` inside the repo):

```
uv venv --python 3.11 .venv
uv pip install --require-hashes -r requirements.lock
uv pip install --no-deps -e .
```

Then name the firm: put `{"name": "<the firm's name as it should appear
as a document author>"}` in `pursuits/web/firm.json` (the workspace
root, beside the pursuits — never in the checkout's `config/`, which
ships in the public mirror). Every buyer-facing document is stamped
with it; while it is missing, documents go out with a blank author and
the downloads record says `unconfigured` (P3-15).

Then prove the copy: `make check` must be green before the first pursuit.
The suite is offline and spends nothing — "Zero spend by default." is the
standing law, and the pilot does not change it: the handoff seam consumes
your seat, not an API key, so no `RFP_LIVE` gate is involved anywhere in
this runbook.

## Start the workbench

One line, from the checkout root:

`.venv/bin/python -m engine serve --handoff --workspace pursuits/web`

On macOS, prefix that line with `caffeinate -i` so idle sleep cannot kill
the server mid-pursuit; other platforms use their own keep-awake tools.

The app is at http://127.0.0.1:8400. The banner confirms the pipeline is
in handoff mode; the assistant and advisor lanes stay FakeCaller. The
`pending-calls/` directory is created inside the workspace at launch — if
it is missing, the flag did not take; stop and fix before any pursuit.

Keep the workspace under `pursuits/` (the default above). The exchange
files carry buyer prompt text; the checkout's ignore rules keep
`pending-calls/` untracked at any depth, but the default workspace is the
posture the pilot was designed around.

`--handoff-timeout` raises the per-call wait if your answering sessions
run long (the default is generous; see docs/pilot/answering-session.md).
Liveness check from a shell: `GET /api/health` reports ok, mode, and
version.

## Start the answering session

1. Make a pilot home directory beside the checkout (not inside it), e.g.
   `~/rfp-pilot/`.
2. Copy `docs/pilot/operator-CLAUDE.md` from the checkout into that
   directory **as `CLAUDE.md`**.
3. Launch Claude Code in the pilot home directory and paste the pilot
   prompt — the fenced block at the top of
   `docs/pilot/answering-session.md`.

The session identity comes from the launch directory: launched in the
pilot home, it reads the operator CLAUDE.md and acts as the answerer; the
checkout's own CLAUDE.md (build protocol) never governs it.

## When a step stalls

A judgment call the answering session never picks up times out after the
configured wait and the job lands as **refused** — an absent operator is a
refusal, not a bug. The request file remains in `pending-calls/` as the
honest record. Start (or fix) the answering session and press **Advance**
in the UI again: the engine re-issues new requests and resumes; pairs are
never deleted, so the audit trail survives the stall.

## When an exit refuses over another client's identifier

Every exit — the rendered submission, each write-back into the buyer's
own forms, the firm-template fill, and a share link at creation — scans
the exact text it is about to hand outward against the identifiers the
knowledge base has ever taken in, less this pursuit's buyer and the
firm. A match is a typed refusal: the downloads list names the file
under what is withheld with the reason, the reason names the locations
(section and slot, or sheet and cell) and a count per location, and the
run carries a `pre_export_leakage` line reading `block`. The matched
text is never in the record; an operator who needs it reads the section
the location names. Fix the passage, run the exit again, and the line
reads `pass`. Contact details, web addresses, street addresses, tax ids
and reference numbers are counted in the report but do not refuse on
their own in this release — the owner's call, so a firm e-mail in a
real proposal does not train anyone to override the refusal.

## Recovery: torn and corrupt files

Every durable record is written atomically or appended with an fsync per
line, so a crash leaves a file either intact, complete, or — for an
append-only record — with one torn FINAL line. Anything else is
corruption, and corruption is evidence: the engine refuses it by name and
never repairs it silently. What to do, by record:

- **A run log (`runs/<run_id>/run.jsonl`) with a torn final line.**
  Automatic. The next resume of that run truncates the torn bytes (fsync'd)
  and records the repair as an `error` line with code `torn_tail_truncated`;
  the runs list shows `torn_tail` until then. Diagnosis from a shell:
  `.venv/bin/python -m engine check-run pursuits/web/<pursuit_id>/runs/<run_id>/run.jsonl`
  exits nonzero and names the torn line.
- **A run log with a torn or invalid line anywhere EARLIER.** Stop. The
  run is evidence — never edit it. The same check names the line number.
  The board marks the pursuit `corrupt` on its own row (the other pursuits
  keep rendering); the next **Advance** opens a new run, and the damaged
  run stays on disk for the build side.
- **A run without a footer (`unclosed` in the runs list).** The job lane
  closes a crashed job's run with a `failed` footer, and a server restart
  closes the runs of jobs it found mid-flight. An `unclosed` run that
  survives a restart is a hard kill; it costs nothing to leave — every
  metric counts only closed runs.
- **The jobs journal (`jobs.jsonl`) with a torn final line.** Automatic at
  the next server start: the torn bytes are truncated (fsync'd) before the
  journal is written again, and the restart proceeds; a complete final
  record that merely lost its newline gets the newline, never a repair.
  (Until 0.9.2 the restart appended onto the fragment and the SECOND
  restart refused the journal as corrupt — that hand-truncate is gone.)
- **The events lane (`events/events.jsonl`), share links
  (`share/links.jsonl`) or pings (`pings/pings.jsonl`) with a torn final
  line.** Automatic at the lane's next write: the torn bytes are truncated
  under the lane's own lock before the new line lands. Until then the
  board's row names the lane under `torn` — every read door tolerates it
  (comments, outcomes, the revise round, the guest page). A torn or
  invalid line anywhere EARLIER in one of these files is corruption: the
  row says `corrupt` and names the file, and for `share/links.jsonl` that
  pursuit's guests get 404 while every other pursuit's guests are
  unaffected. Stop; the file is evidence.
- **Revoking a share link while a job is running.** Works — revoke is the
  kill switch and never waits on the job lane (until 0.9.2 it was refused
  with 409 for the job's whole run).
- **An upload named like a lane's own record.** Refused (422) by name:
  `roles.json` at the inbox door; `meta.json` and any `*.superseded.json`
  at the addenda door. The record is never overwritten by an upload.
- **A checkpoint (`checkpoints/<stage>.json`) that will not parse.** Delete
  that one file; the stage re-runs from its predecessor's artifact on the
  next **Advance**. Never delete `*.frozen.json` — a frozen artifact is
  rewritten only by resubmitting its gate.
- **`drafts/annotated-draft.json` unreadable.** The board's row says
  `corrupt` and names the file; the next **Advance** moves the unreadable
  bytes aside as `drafts/annotated-draft.json.corrupt-NNN` (nothing is
  destroyed), re-runs validation and rewrites it (the annotated draft is
  rebuilt, never patched), and records the repair as an `error` line
  (`annotated_draft_unreadable`) in the validation run.
- **`drafts/draft.json` unreadable.** Never rebuilt by the engine — it holds
  the review rounds' human edits. The next **Advance** refuses by name
  (the job reads `refused`, the file is untouched); the build side restores
  it from `revisions/draft.revN.json`.
- **`brief.json` or `plan.json` unreadable.** The board names the file. If
  a frozen copy exists (`brief.frozen.json`, `plan.frozen.json`) it is the
  authoritative record and the build side restores the live file from it;
  the pilot host does not hand-edit either.
- **The knowledge base.** Out of this runbook's scope: a KB file problem is
  reported to the build side, which runs the reconciliation tooling.

## Keeping the copy honest

- `git status` clean, always. Anything that needs an engine change goes
  back to the build side; the fix arrives as a new pinned tag.
- Nothing real enters the work environment before the data-governance and
  IP-provenance call-out lands — that trigger binds regardless of how far
  the pilot gets.
- The exchange pairs in `pending-calls/` are the audit record of every
  judgment call; leave them in place.
