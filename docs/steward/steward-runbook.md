# The steward runbook

The knowledge base grounds every draft the engine writes. The steward's
job is to keep it true: bring documents in, review what the machine
proposes, and take a client's material out completely when asked.
Nothing becomes a card without a steward's acceptance, and every change
is attributed — the store snapshots before and after each merge, and
each run records the snapshot it drafted against.

## Bringing a document in

`python -m engine kb ingest --file <doc> --client <name>
--pursuit <id> --date <YYYY-MM-DD> --wire <wire.json>` reads a
firm-authored document (docx is the primary path), splits it into
heading-shaped chunks, and mints cards with content-anchored ids.
Until real-data onboarding opens (A1), the model's annotation pass is
supplied as a scripted `--wire` file; the live call is the same seam.

Two gates stand between the file and the store. The anonymization gate
scans every element, card, and drafted proposal against the client's
identifiers — one finding blocks the **entire** ingest, nothing
persists, and the findings route to a restricted audit queue. The
claim gate never writes facts: claim-like statements found in the text
become **proposals** for fact-sheet atoms, and each one waits for a
steward to accept it with an owner and a verified date.

## Re-ingesting and the reconciliation report

Ingesting a newer version of a document you ingested before is safe by
design: cards match on content, not position. The reconciliation
report (under `kb/reconciliation/`) sorts every prior card into four
buckets — **matched** (unchanged), **drifted** (content moved; the card
keeps its id, its edit history, and its governance, and increments its
version), **created** (new), and **orphaned** (nothing in the new
version matched it). Orphans are retained, never deleted — they wait
in the orphan queue for a steward to deprecate, edit, or leave.

## The proposal queue

Every write path is a proposal: the curation screen, the workbook
import, ingestion's claim promotions. Review them in the KB screen's
steward inbox. Accepting a fact-sheet card **refuses** until you
supply its owner and verified date — a fact nobody vouches for is not
a fact. Deprecating a card that is still cited, or touching one under
legal hold, refuses and names why.

## Bulk edits by workbook

**Export workbook** on the KB screen gives you every card as a
spreadsheet row. Edit in Excel, then import it back: the import is
all-or-nothing — any error (an unknown id, a locked governance column)
refuses the whole sheet and lists every bad cell, and each clean change
becomes one proposal in the queue. Bulk editing never bypasses review.

## Purging a client

`python -m engine kb purge --client <name> --actor <you>` removes a
client's material at every layer — retained sources, canonical models,
cards, and any draft content that cited a purged card (the whole
artifact goes; drafts are regenerable, quiet holes are not). The purge
writes a full accounting and then sweeps the store to prove the name
is gone; it raises rather than finish with anything unaccounted. Cards
under legal hold are held, reported, and hold their parents.

## Health checks

`kb stats` prints the chunk-size distribution — size is recorded,
never enforced, so an outlier is an extraction finding, not content to
split. `kb snapshot` prints the store's content id; two runs are
comparable only when their snapshots and config digests match.
`kb where-used <name> --actor <you>` answers a right-of-review
question; provenance reads are access-logged, never casual.
