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

## Ingesting a firm document

`python -m engine kb ingest --file <doc> --client <name> --pursuit <id>
--date <YYYY-MM-DD> --live` reads one firm-authored document into the
KB (P28). Two readers see it: the ingestion agent, which annotates the
chunks and lists the identifiers it finds, and the anonymization
reviewer, a second reader of independent lineage that lists identifiers
only and never sees the first list. Code adds what a regex can find
before either is trusted — emails, phones, web addresses, street
addresses, EIN/SSN-shaped numbers, contract/PO/RFP/invoice numbers — and
the union is substituted with typed placeholders: `[CLIENT]`, `[FEE]`,
`[REFERENCE_NAME]`, `[ORGANIZATION]`, `[CONTACT]`, `[URL]`, `[ADDRESS]`,
`[TAX_ID]`, `[REFERENCE_NUMBER]`; a type the readers name that the table
lacks falls to `[REDACTED]` and is reported. Then the scan runs over
everything that would persist: an identifier's distinctive words,
acronym, possessive, wrapped form, a fee's K/MM/rounded restatements,
and every structured class unconditionally. One hit and the document is
BLOCKED — no card, no canonical model, the raw file retained behind the
access log for the audit human the report names; the command prints the
residue's location and matched text to your terminal (never to a
record). A block is a finding to act on, not a number to watch. The
scan set is EVERY string the ingest persists, enumerated by one helper
(the canonical elements, every claim text, each card's title, summary,
body and question forms, each proposal note) — a persisted field is
either in that set or it is not written (P29a). The document itself is
recorded by a content id and a neutral handle; its filename lives only
in the restricted meta, behind the access log, never in a card, a
proposal or a run log.

`--live` refuses without `RFP_LIVE=1`, a key and a priced table, and
spends nothing until all three hold; `--budget-usd` (default 5) bounds
the one document's two reads. Offline the same door takes `--wire` and
`--reviewer-wire`, scripted replies for the two readers — the suite's
path, never the production one. A completed response workbook (the buyer's questionnaire with the firm's
answers beside the questions) goes through this same door directly —
`--file <xlsx>`, one card per answered question, kind `past_response` —
or first through `python -m engine kb pair` as editable markdown; the
steward runbook's "Bringing a completed response workbook in" section
says what the read skips and when it refuses.

Nothing is minted twice. A card's id is a hash of its body, so a body
the store already holds is skipped and the terminal names the id; a
near duplicate — vocabulary overlap at or above the dedup floor in
`engine/kb/rank.py` — merges: when one text's vocabulary wholly
contains the other's the fuller one survives, otherwise measured edit
survival, then outcome, then id decide, and the absorbed card's sources
fold into the survivor. The terminal prints `absorbed -> survivor` with
the score and which side survived. The floor was set on the synthetic
seed corpus; its first measure on real answers is A1's, read off the
merges the steward sees at the first real bulk ingest — `--dry-run`
prints that list before anything is written (P34a).

The taxonomy above is the domain's as of P28 (the owner's call); A1's
real-material review may add a class — that review is the closer named
at the `TODO(spec-gap)` in `engine/kb/anonymize.py`, and the register
records what arrived. The eval corpus (`evals/anonymization/`, 44 cases)
carries an adversarial case per mechanism; the release record's
anonymization lane reports `n_blocked` (how many synthetic cases the
gate refused rather than delivered) and `measures.live` — the recorded
measure of the LIVE readers, fresh only while every input it names —
the case list, the documents, the gate code, the reader prompts, the
model pins — and the model configuration still match, `not_measured`
naming what moved otherwise (P29a); every run rebuilds every case's
store from nothing, so the record measures the readers under test and
never a previous run's cards. That record is A1's acceptance line;
`docs/uat/a1-anonymization-live.md` is the run.

The flywheel passes the same scanner: a reviewer edit, comment, waiver,
answered gap or hand-typed case block that still names a party after
placeholdering is not proposed — the accept and writeback responses list
it under `blocked` by location (P1-46; the write-back door's record
joined at P29a, P3-23 — `skipped` there is benign skips only). An
answered gap reaches the proposal queue through ONE door whichever
lane offered it (Gate 0's opt-in, a ping answer's opt-in, the accept
route) — the door cleans the question and the answer and scans them
(P29a, P1-49); a proposal that door finds already open and dirty is
`voided` with a curation-log line and the gap re-proposed clean, and a
new card mints only from a body the accept-side scan passed.

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

## What the assistant may open

The assistant has two read doors onto a card — `open_card` and
`card_detail` — and both honour the same withholding: a card under
`use_restriction` (D2) or one a steward deprecated is refused at either
door, with a `kb_retrieval` line on the run log naming the door it fired
at (`targeted_open` or `card_detail`) and the card under `excluded`. Only a
card that passed that predicate earns the right to be cited. Your own KB
screen and the curation route keep the full view — withholding is a
retrieval control, not a record edit.

## When something breaks

Read the failing test's message first — the suite's errors are written
to name the decision they enforce. If the suite is red after a pull,
the environment drifted: rebuild the venv from the lock. If a purge
sweep reports findings, stop and treat it as an incident — the sweep
names the file that still carries the name. Nothing in this system
fails silently by design; a quiet success after a loud failure is the
thing to distrust.
