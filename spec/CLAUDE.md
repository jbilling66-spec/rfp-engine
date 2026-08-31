# CLAUDE.md — standing rules for building RFP Engine v2

*Read this first, every session. It is short on purpose. The build plan is `handoff/WORK_PACKAGE_HANDOFF_V2.md`; the normative design decisions are `DECISION_LOG.md`. This file is only the rules that apply to every line of code regardless of which work package you are in.*

*(If you use tools that read `AGENTS.md` instead, copy this file to that name — same content, one source.)*

---

## 1. Delete rather than deprecate — with three exceptions

v2 is a redesign, not a migration. Do not preserve v1 code, v1 interfaces, v1 naming, or v1 abstractions for their own sake. Do not write a compatibility shim. Do not leave a dead branch behind a flag "in case." If v1 did it differently and the spec says otherwise, the spec wins and the v1 way goes away.

Three things are exceptions, and they are exceptions because they are **data, not code**:

- **The `target-slot` schema and the hosp-erp/OTAS structure fixtures.** These are the permanent regression bench (WP10). Their format *is* a contract. Changing it doesn't modernize anything, it destroys the only continuous quality series that spans both engines.
- **Anything already ingested into the knowledge base.** A migration is fine. A "we'll re-ingest it" is not — provenance, use-restrictions, and legal holds do not survive a casual reload, and one of them is a client commitment.
- **The write-back path's behavior against real buyer files.** Reimplement it if the spec calls for it, but every quirk it currently handles is a client document it did not corrupt. See rule 5.

The line: **break interfaces freely, never break data or the evidence of past behavior.**

## 2. Simplest implementation that fully meets the requirement — and here is what "the requirement" includes

Prefer the direct version. No framework where a function will do, no abstraction with one implementation, no configurability nobody asked for, no defensive layer against a failure that hasn't happened. If you are writing a base class, a plugin registry, or a strategy pattern, stop and write the concrete thing.

But "current requirements" here includes controls that *look* like ceremony and are not. Do not simplify these away; if one seems unnecessary, that is the signal to ask, not to remove:

| Looks like | Actually is | Why it stays |
|---|---|---|
| Indirection in the metric layer | Definition governance (R6) | Two screens disagreeing about edit-survival is how the numbers stop being believed |
| An over-detailed claim tier field | The control that buys v2 its boldness (E2) | Without Tier-1 blocking, "draft confidently" is "fabricate confidently" |
| A restricted provenance field nobody reads | The anti-leakage boundary (S3, S8) | One client's details appearing in another's response ends the program |
| `seq` ordering on run-log lines | Correctness under concurrency (O-series) | Timestamps from parallel agents do not order |
| A boolean where a percentage would be nicer | The anonymization result (R13, E4) | Required recall is 1.00; an average hides the only value that matters |
| Reviewer-effort capture "we can add later" | Unrecoverable measurement (R3) | A review session that happened uninstrumented is gone forever |

Everything *not* on that list is fair game for aggressive simplification, including things this spec describes in more detail than the code needs.

## 3. Established libraries over custom implementations — with a supply-chain condition

Do not hand-roll retries, backoff, JSON Schema validation, diffing, date handling, DOCX manipulation, or agent orchestration primitives the Claude Agent SDK already provides. A well-maintained dependency has absorbed edge cases you will otherwise meet in production.

Two conditions, because this system handles confidential client material:

- Every dependency is pinned with a lockfile, and its license is checked before it lands. A permissive-license assumption is not a license check.
- **No new dependency enters the ingestion, anonymization, write-back, or export path without a human reviewing it.** Those four paths touch client-confidential text and buyer files. Elsewhere, add what you need.

One such dependency is already reviewed and decided: the extraction layer (`handoff/EXTRACTION_AND_SCALE_SPEC.md`, decisions X1–X7). It carries a proof gate you must run before integrating it, and a fallback if it fails. Model weights are vendored internally with recorded digests — **no runtime fetch from a public model hub in production**, ever.

## 4. The schema is the contract; the decision log is normative

If code and schema disagree, the schema is right and the code is a bug. Schema changes ship in their own commit with a one-line rationale, never bundled into a feature.

If you are about to do something that contradicts a numbered decision in `DECISION_LOG.md`, **stop and surface it.** Those numbers came from requirements sessions; some of them look arbitrary and are load-bearing. Contradicting one may well be correct — but it is a decision to be made explicitly, with the entry updated, not absorbed silently into an implementation.

## 5. Behave like the system you are building

The engine's central honesty rule is that it asks a human rather than inventing. Apply it to yourself: when a requirement is genuinely ambiguous, leave a marked `TODO(spec-gap)` with the question and keep building around it. Do not resolve the ambiguity by inventing a plausible requirement — a guess that reads as a decision is worse than an open question, because nobody knows to check it.

Two corollaries: **never widen an agent's tool grants to make a test pass** (least privilege is S5; a green test bought that way is a control removed), and **no real client text in fixtures, tests, or sample data** — synthesize it or use the anonymized fixtures.

## 6. Prompts are product

Agent prompts and configs live in version control as files, not as string literals scattered through the code. Every release records the eval results it passed (N3, E7). A prompt edit is a product change and gets the same review a code change gets.

---

## Working order

`README.md` for the reading order, then the work package you are in. Before writing code that touches anything v1 built, read `handoff/V1_RECONCILIATION.md` — the salvage audit runs first for a reason, and it is the only structured chance to recover the edge cases v1 learned the hard way.
