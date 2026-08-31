# The committed knowledge-base corpus is wholly synthetic

Every file in this tree — cards, canonical documents, restricted
provenance, sources — describes an **invented** consulting firm and
invented clients, built as the engine's test corpus — the source of truth
is `tests/kb/fixtures/corpus.py`. No real organization, person, fee, or
engagement appears anywhere in it.

The invented clients: Meridian Health Partners, Cascade Valley Medical
Center, Harborlight Insurance Group, Bluegrass Municipal Utilities,
Tallgrass County Schools (plus the synthetic buyer Northwind Regional
Health in the fixtures). The invented people (Dana Whitfield, Priya
Raghavan, Marcus Ellison, Sofia Camacho, Aaron Tuck) and every dollar
figure are equally fictional.

**About `kb/restricted/`:** the provenance maps there (identifier →
category, e.g. a fee string mapped to `FEE`, a name to `REFERENCE_NAME`)
look exactly like de-anonymization data — because that is what they are,
for the synthetic corpus. They exist to prove the anonymization controls
work: cards retrieve with identifiers stripped, and only actors granted in
`config/kb-access.yaml` may read the mapping back, with every access
logged. When you seed your own corpus, this design is what keeps your real
client identifiers out of retrievable text.

An adopting organization replaces this corpus with its own via the
ingestion doors — see `docs/graph/doors.md` and
`docs/steward/steward-runbook.md`; the committed corpus stays as the
test bench.
