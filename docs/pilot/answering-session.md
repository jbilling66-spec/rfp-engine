# The answering session

*Audience: the work-side Claude Code session that supplies judgment-step
completions through the handoff seam — and the pilot host, who launches it. The
protocol string, field names, filenames, and defaults stated here are
checked against the handoff caller's own source — that is what the drift
test checks, and no more (`tests/contracts/test_pilot_docs.py`;
`engine/llm/handoff.py` is the implementation and the authority).*

## The pilot prompt

Paste this to launch the session (from the pilot home directory — see the
runbook):

```
You are the answering session for the RFP Engine pilot. Read
docs/pilot/answering-session.md in the engine checkout beside this
directory and follow it exactly: watch the serve workspace's
pending-calls directory, answer each request honestly on its own
merits, write every response atomically (temp file in the same
directory, then rename), echo the request's seq and agent, declare
the real model that answered, and never delete, move, or rewrite an
exchange file. Answer only what a request asks.
```

## The exchange

The engine writes a request file into the workspace's `pending-calls/`
directory and blocks, bounded, until the matching response appears. The
protocol is `handoff/v1`. Filenames pair by sequence number:

- `call-0001.request.json` — written by the engine
- `call-0001.response.json` — written by you

A request carries `protocol`, `seq`, `agent`, `tier`, `prompt`, `system`,
`pursuit_id`, and `run_id`. The `prompt` (with its `system` preamble) is
the whole task; `agent` and `tier` tell you which role in the pipeline is
asking and at what depth to think.

## Your response

A response is a JSON object with four required fields and two optional
ones:

- `seq` — echo the request's number exactly
- `agent` — echo the request's agent exactly
- `model` — the REAL model that answered (e.g. the model this session is
  running). A `fake-` prefix is refused loudly: it would price the call at
  the synthetic table and fabricate spend. Honesty here is load-bearing —
  the run log records what actually judged.
- `text` — the answer itself, exactly what the prompt asked for
- `input_tokens`, `output_tokens` — optional; supply them if you know
  them, else the engine estimates.

An echo mismatch on `seq` or `agent` is refused: the answer must name the
request it answers.

## Discipline

- **Write atomically**: build the response in a temp file in the same
  directory, then rename it into place. The engine tolerates a torn read
  by polling past it, but atomic writes are the discipline — a half-read
  never becomes an answer.
- **Never delete, move, or rewrite a pair.** The answered pair on disk IS
  the audit record; an unanswered request left by a timeout is the honest
  record of the timeout.
- **Answer in order when you can**, lowest `seq` first — the engine waits
  on one call at a time.
- **Refuse honestly.** If a request asks for judgment you cannot ground,
  say so in `text` rather than inventing an answer; a wrong answer flows
  into a draft, a refusal surfaces to a human.

## Timing

The engine waits a bounded time per call — default 900 seconds — then the
job lands as refused and the request file remains. Nothing is lost: when
the operator presses Advance again, the engine issues NEW requests with
fresh sequence numbers (it never overwrites an earlier pair). The pilot host can
raise the wait with `--handoff-timeout` at serve time.

## What this costs

Nothing, by design: "a handoff call consumes an operator's seat, not an
API key" (the caller's own docstring). Every result is recorded as
`handoff/<declared model>` with a marginal cost of zero — the transport is
unmistakable in every trace, and no API key exists anywhere in the pilot.
