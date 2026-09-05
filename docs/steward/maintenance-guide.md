# The maintenance guide

How to keep the engine healthy on any machine, and what its records
mean. The repository is the durable copy of everything except local
pursuit workspaces and the gitignored `tripwire-local/` files (the
restricted-token list is machine state, deliberately never tracked —
back it up separately). A dead laptop costs nothing that was pushed,
plus that one restore.

## Setting up a machine

Clone, then build the environment exactly this way: `uv venv
--python 3.11 .venv`, then `uv pip install -r requirements.lock -e .`.
Restore `tripwire-local/tokens.txt` (the restricted-token list; the
suite fails loudly without it — in a public clone the committed
attestation covers this instead). Run `make check` before anything else — every test must pass on a
fresh machine with zero network and zero model spend; a failure here
is a finding, not noise. For the document-extraction container: set
the Docker VM memory to 16GB or more, `make gate-image`, download the
model weights, and verify them against the **committed** digest
manifest before any freeze — a digest match is the continuity proof
between machines; a mismatch is a finding, never an auto-refresh.

## The daily commands

`make check` is the whole offline suite — FakeCaller only, spends
nothing, and is the gate before every commit. `python -m engine serve
--workspace pursuits/web --port 8400` starts the workbench; it binds
to the machine itself only, by decision — putting it on a network is
the Azure phase's job, not a config flag. `make slice` proves the
end-to-end pipeline headless; `make eval` runs the release gates. Those
gates guard themselves (P26b-3): every lane's rate refuses below a
declared floor equal to the committed corpus size (shrinking a suite is
a deliberate edit of the floor, with its B-entry); the two live
baselines carry a sibling `baseline.lock.json` that only a live
re-baseline writes, so an edited number is refused by name; and the
mapper re-measure reads its baseline from the shipped, drift-tested
`evals/mapper/recorded.json` and refuses `live=True` without `RFP_LIVE=1` and a traced live caller.

## Spending money

The default caller is fake and free, everywhere, always. Live model
calls require `RFP_LIVE=1` and pass through a cost ceiling that aborts
the run loudly rather than run up a bill. The price table
(`config/models.yaml`) is dated and signed: when a listed price
expires, the file must be re-signed before the next live run — an
unpriced model refuses to run rather than bill at a guess.

## Changing dependencies

Dependency changes are deliberate: edit `pyproject.toml`, re-pin
`requirements.lock` (regenerate with `make lock` and review the diff — since P26a the lock carries hashes, and hand-splicing a hashed lock is not a thing; the lock's line order is
part of its diff hygiene), rebuild the gate image so the extraction
lock re-freezes, and let the suite's lock test confirm the environment
matches the pins. A dependency nothing imports gets removed, not kept.

## The records and what they are for

These four files live in the private canonical repository and do not
ship in the public mirror — a fork starts records of its own under the
same protocol (see `CLAUDE.md`).

`DECISIONS.md` holds every product decision as a numbered B-entry —
the why behind the code; read it before relitigating anything.
`ROADMAP.md` is the phase board; a phase flips DONE only when its
named acceptance command passed. `SESSION.md` is the living state —
what is running, what is next, what is parked — overwritten at each
session close. `lessons.md` is one screen of work-rule corrections.
If the repo and a memory disagree, the repo wins.

## When something breaks

Read the failing test's message first — the suite's errors are written
to name the decision they enforce. If the suite is red after a pull,
the environment drifted: rebuild the venv from the lock. If a purge
sweep reports findings, stop and treat it as an incident — the sweep
names the file that still carries the name. Nothing in this system
fails silently by design; a quiet success after a loud failure is the
thing to distrust.
