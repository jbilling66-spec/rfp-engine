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
uv pip install -r requirements.lock -e .
```

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

## Keeping the copy honest

- `git status` clean, always. Anything that needs an engine change goes
  back to the build side; the fix arrives as a new pinned tag.
- Nothing real enters the work environment before the data-governance and
  IP-provenance call-out lands — that trigger binds regardless of how far
  the pilot gets.
- The exchange pairs in `pending-calls/` are the audit record of every
  judgment call; leave them in place.
