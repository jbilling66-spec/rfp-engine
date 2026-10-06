# The steward runbook

The knowledge base grounds every draft the engine writes. The steward's
job is to keep it true: bring documents in, review what the machine
proposes, and take a client's material out completely when asked.
Nothing becomes a card without a steward's acceptance, and every change
is attributed — the store snapshots before and after each merge, and
each run records the snapshot it drafted against.

## Bringing a document in

`python -m engine kb ingest --file <doc> --client <name>
--pursuit <id> --date <YYYY-MM-DD> --live` reads a firm-authored
document (docx is the primary path), splits it into heading-shaped
chunks, and mints cards with content-anchored ids. Two model readers
see it — the ingestion agent, which annotates the chunks and lists the
identifiers it finds, and a second, independently written anonymization
reviewer that lists identifiers only — and code finds the structured
ones (emails, phones, web addresses, street addresses, tax ids,
contract and PO numbers) before either reader is trusted. The union is
substituted with typed placeholders. `--live` refuses without
`RFP_LIVE=1`, a key and a priced table, and spends nothing until all
three hold; offline, the suite's path takes `--wire` and
`--reviewer-wire`, scripted replies for the two readers. The store
never records the file's name — the document is keyed by a content id
and a neutral handle, and the filename lives only in the restricted
meta behind the access log (a file named after the client used to reach
the proposal queue by its name; P29a). The maintenance guide's
"Ingesting a firm document" section carries the taxonomy, what a block
means, and the live measure A1 records.

Two gates stand between the file and the store. The anonymization gate
scans every element, card, and drafted proposal against the client's
identifiers in every form the scan knows (distinctive words, acronym,
possessive, restated fees) and against every structured class
unconditionally — one finding blocks the **entire** ingest, nothing
persists, and the findings route to a restricted audit queue. The
claim gate never writes facts: claim-like statements found in the text
become **proposals** for fact-sheet atoms, and each one waits for a
steward to accept it with an owner and a verified date.

## Bringing a completed response workbook in

Most delivered responses are the buyer's own questionnaire workbook
with the firm's answers typed into the response column. `python -m
engine kb ingest --file <xlsx> --client <the buyer> --pursuit <id>
--date <YYYY-MM-DD> --live` reads one directly, exactly as it would a
Word document: one card per answered question, titled by the buyer's
question, bodied by the firm's answer, the buyer's own name
placeholdered wherever it appears (the owner's call), the card's kind
`past_response`. What the read leaves out, it names on the terminal by
sheet and row, never by the cell's text: an unanswered question, an
answer with no question beside it, an answer that is only a number, a
fee or a yes/no (a figure never rides into the corpus), a formula cell
with no cached value, a hidden sheet, row or column, a sheet with no
question and response columns, and a pricing sheet. Hidden or uncached
content that was skipped marks the document's cards `degraded` —
ingested, flagged, like any imperfect parse. A workbook with nothing to
pair, a damaged file, or a format the knowledge base has no reader for
(a PDF, say) is refused by name and nothing is written, not even a run
record. To read and correct the text before the two readers are paid
to read it, `python -m engine kb pair --file <xlsx> --out <md>` writes
the same pairing as markdown — zero spend, yours to edit — and `kb
ingest --file <md>` then takes it in as the same kind; that preview
path refuses an answer whose line would read as markdown structure (a
line starting `# `, a `| … |` row), which the direct path does not.
Only workbooks whose answer sits beside its question on the same row
pair today; an answer beneath its question is a shape the build side
has not seen yet — send one, with the names stripped.

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
import, ingestion's claim promotions — and the flywheel: a reviewer's
edits, comments (with the agent's reply), waivers and answered gaps
reach the queue when a pursuit is accepted, a hand-filled case block
when its write-back is confirmed, all in the reviewer's own words.
Review them in the KB screen's steward inbox. Every row shows the diff,
where it came from (the pursuit, the events, a guest chip when the
signal came from outside the firm) and **where it lands** if you accept
it. Accepting is never nothing:

| proposal | lands in |
|---|---|
| a card's front matter | the card |
| a reviewer's lesson about a card | the card's lessons list — visible in the row, never drafted from |
| a voice, playbook or validation-tuning note | the steward notes the drafter reads (the accepted proposal is the note; the KB screen lists them) |
| a deprecation | a `deprecated` block on the card — retrieval withholds it, nothing is deleted |
| a new card | a new card |

Accepting a fact-sheet card **refuses** until you supply its owner and
verified date — the row asks for them — because a fact nobody vouches
for is not a fact. Deprecating a card that is still cited, or touching
one under legal hold, refuses and names why. Nothing in the queue is
ever deleted: a rejected proposal is evidence, and a proposal the
system withdrew (`voided` — one the accept-time re-check found dirty,
or one derived from a card a client purge removed) stays on the record
with its reason. A batch that names the same proposal twice refuses
before anything applies. The one purge door you have is
the client purge below; a pursuit-scoped purge of what a pursuit taught
exists as library code with no door until the A6 organization screen.

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
under legal hold are held, reported, and hold their parents. The purge
also follows lineage INTO your queue: a proposal derived from a purged
card is voided (named under `voided_proposals`, one curation-log line),
so accepting it later can never re-mint the material — and a re-ingest
of the same document meets that voided record rather than re-opening
it. A retained source that has no meta record (a crash between the two
writes that store one) belongs to no client and no card, so every purge
removes it and names it under `l0_orphans_removed`; the sweep is never
CLEAN over one.

## Health checks

`kb stats` prints the chunk-size distribution — size is recorded,
never enforced, so an outlier is an extraction finding, not content to
split. `kb snapshot` prints the store's content id; two runs are
comparable only when their snapshots and config digests match.
`kb where-used <name> --actor <you>` answers a right-of-review
question; provenance reads are access-logged, never casual.
