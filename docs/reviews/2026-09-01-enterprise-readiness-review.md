# Enterprise-readiness review — 2026-09-01

*An exploratory, no-code-changes review of the full repository against external
feedback that scored the architecture 8.5–9/10 and enterprise readiness
5.5–7/10. Six parallel deep-dive reviews (workflow/gates, knowledge
management, evaluation, security, collaboration/product, production
engineering) plus a fresh-clone verification run. Every claim below carries
file evidence; every gap is tagged either **[deferred → phase]** (already
written down with a named closer, per CLAUDE.md rule 5) or **[silent]**
(a gap this repo's own rules say must not stay silent).*

*Verification baseline: a fresh clone of this branch went green on
`make check` — 1,446 tests passed in 5:44, zero network, zero spend —
exactly as the README promises.*

---

## 1. Verdict on the external feedback, line by line

### "Strength #1: The gates are excellent" — TRUE, with three asterisks

Verified: exactly **three** formal gates, correctly positioned and enforced in
layers — the driver stops honestly without a decision
(`engine/pipeline/driver.py:206-210, 253-258, 276-281`), and drafting
*independently* refuses without an approved plan and the physical freeze files
(`engine/drafting/draft.py:81-95`), so even a caller that skips the driver
cannot draft past a missing Gate-2 freeze. Gate decisions are
idempotent-convergent, attributed (actor + timestamp in the artifact, the
checkpoint, and a schema-validated run-log line), and rejections require notes
that feed the redo. The gate *UX* is genuinely informed review — assumption
registers, per-theme kill boxes with citations, gap dispositions with nothing
preselected (`engine/web/server.py:1477-1479`), reason-required waivers.

The asterisks:

1. **"Human approval" is a free string.** `approve_gateN` takes `actor` as
   unauthenticated text; the CLI slice auto-approves gates programmatically
   (`engine/cli/slice.py:168` — honestly flagged `auto_approved`, but nothing
   structural separates "a human decided" from "code passed a string").
2. **There is no formal gate on the highest-stakes transition** — validated
   draft → export is guarded by refusal logic + an accept stamp
   (`engine/assembly/docx.py:66-77`), not the same decided-gate machinery.
3. **Approval timestamps are client-suppliable** (`engine/web/server.py:101-102`
   — `payload.get("at")` wins over server time). Deliberate (the no-wall-clock
   rule), but an auditor flags backdatable approvals immediately.

### "Strength #2: Freezing is sophisticated" — TRUE IN DESIGN, INCOMPLETE IN ENFORCEMENT

The freeze mechanics are real: approval writes a byte-equal frozen copy through
the validated serializer, records its sha256, downstream reads only the frozen
copies, and the **plan** hash is bound into the draft envelope and re-verified
at validation (`engine/validation/validate.py:83-86`). The addendum replan is
the one legitimate mutation door and it is done right — the old frozen plan is
archived intact and existing drafts void by hash mismatch, not convention
(`engine/web/addenda.py:130-143`).

But the claim "downstream agents can't mutate upstream assumptions" is only as
strong as its weakest link, and there are two:

- **`brief.frozen.json` is never hash-verified downstream.** Gate 1 records
  `frozen_sha256` (`engine/strategy/gate.py:217`) but no reader ever compares
  it — drafting and validation consume the frozen brief unchecked
  (`draft.py:111`, `validate.py:89`). Post-approval tampering with the win
  themes or buyer terms flows silently into buyer-facing prose. **[silent]**
- **Frozen files are ordinary writable JSON.** `write_artifact` has no
  write-once check, no chmod, no separate store
  (`engine/workspace/pursuit.py:46-55`). Freezing is a convention plus partial
  hash verification, not immutability. **[silent]**

### "Strength #3: Artifact separation" — the TRUEST claim

The artifact pipeline is real, schema-validated at every write (Draft 2020-12,
violation = nothing lands, `engine/contracts/validate.py:54-60`), and — rare
anywhere — the architecture docs are machine-compared against the code in both
directions (`tests/contracts/test_graph_artifact_flow.py`,
`test_graph_doors.py`). Caveats: schema enforcement is **write-only**
(`read_artifact` is raw `json.loads`, `pursuit.py:57-58`), and the `write_json`
escape hatch carries real decision-adjacent state (events, addenda, revision
rounds) with no schema at all (`pursuit.py:60-69`). **[silent]**

### "Weakness #1: workflow architecture more than complete product" — CORRECT

The most accurate line in the feedback. Backend collaboration primitives
(comments with agent replies, trust-quarantined guest share links, revision
archives with server-computed diffs, SME ping lanes with 24h escalation) exist
in disciplined form — but the UI covers roughly **15 of 50+ API routes**
(`engine/web/static/app.js` vs `docs/graph/doors.md`): no waiver, ping, share,
export, download, write-back, revision-diff, effort, outcome, or KB-import
screens. The operator guide is honest that "the pilot host runs these for
you" via curl. A guest opening a share link gets **raw JSON**
(`server.py:920-941`) — there is no guest-facing page. Integrations
(SharePoint/Teams/CRM/email/DMS): **zero code, zero seams** beyond the SSO
header stub. Commercial modeling of the deal (fees, margin, staffing, rate
cards for the *response*): absent — `config/rates.yaml` is explicitly a
synthetic *internal cost* card for effort metrics, and unlike nearly every
other gap in this repo, **no documented deferral names pricing/staffing as
future scope** in this mirror. **[silent — the notable rule-5 breach]**

### "Weakness #2: knowledge retrieval is where the moat must develop" — HALF RIGHT

Wrong half: provenance and approval governance are not gaps — they are the
strongest engineering in the repo. Restricted provenance split with
access-logged, fail-closed de-anonymization (`engine/kb/provenance.py:70-87`),
purge that cascades over `derived_from` with a post-purge sweep
(`engine/kb/purge.py`), proposal-with-diff stewardship where new facts refuse
acceptance without owner + verified_date (`engine/kb/curation.py:296-301`),
content-anchored card identity that survives re-ingestion, and a fully closed
edit-survival feedback loop (`engine/flywheel/attribution.py`, `survival.py`).

Right half:

- **Retrieval is lexical BM25 over frontmatter with no persistent index** —
  every query re-reads and re-parses **every card file** and rebuilds idf from
  scratch (`engine/kb/store.py:141-145`, `retrieve.py:151-169`). Would not
  survive 10,000 documents. Embedding seam declared
  (`rank.py:3-4`) **[deferred → A-phase]**, but the O(corpus)-per-query cost
  is fixable today with a snapshot-keyed cache. Retrieval floors are
  self-admittedly "fitted to 24 cards that A1 replaces" (`rank.py:26-34`).
- **Win/loss never reaches content.** `outcome_backlabel` exists only as a
  schema enum — no engine code writes one — and the kb-card schema's claim
  that "retrieval prefers won" is **false in code** (sort key at
  `retrieve.py:178-180` never consults `outcome`). A doc/code contract
  mismatch in a repo whose law is "schema is the contract." **[silent]**
- **No conflict detection between KB entries.** Two cards asserting different
  values for the same fact coexist silently; the only contradiction machinery
  is per-draft cross-section consistency (`engine/validation/checks.py:202-230`),
  which fires only after a conflict reaches a draft. **[silent]**
- **No typed content model for resumes/staffing or rate cards** — no
  `doc_kind`, no person entity, no expiry on bios or credentials. RFP
  responses live or die on staffing tables; today these are prose chunks.
  **[silent]**
- Corpus-layer freshness is zero — `review_due` staleness exists only on the
  fact-sheet layer (`curation.py:44-59`); a five-year-old exemplar ranks like
  last month's. **[silent]**
- Citation grain stops at the **section** (cited ⊆ opened ⊆ returned enforced
  at write time — excellent), not the sentence; only audited Tier-1 claims get
  claim→fact-card links.

### "Weakness #3: evaluation infrastructure is critical" — RIGHT SCORE, PARTLY WRONG REASONS

Better than the critique assumed: hallucination/citation control is
**code-enforced, not judge-vibes** — a claim not verbatim-present in delivered
prose is dropped as hallucinated (`engine/validation/claims.py:106-112`), an
invented fact reference blocks Tier-1 (`audit.py:92-96`), the retrieval
emitter refuses at write time to record a citation outside the opened set, and
a trajectory suite asserts those invariants on real run logs
(`engine/evals/trajectory.py:46-114`). Measurement hygiene is exceptional:
four-way fingerprint locks (prompts/cases/model/scorer) stale a recorded
number on any drift (`engine/evals/cases.py:44-80`), held-out splits, benign
controls, one shared scorer, and a hard refusal to fake model numbers under
FakeCaller.

Worse than the critique assumed:

- **Nothing about output quality is measured at all.** Drafter rubric,
  red-team accuracy, win-theme alignment, the consistency model half — every
  quality lane is an honestly-labeled `not_measured_live` stub
  (`engine/evals/run.py:272-293`). The buyer-persona red-team score is
  explicitly advisory because uncalibrated. **[deferred → A3/A4]**
- **Judge calibration has no design and no human-label set** —
  `judge_calibration: not_performed` on every release record.
  **[deferred → A4]**
- **No historical-RFP corpus, no human-vs-AI benchmark machinery** — only
  metric definitions (`win_rate`, `cost_delta_vs_baseline`) whose source
  streams are declared unsourced (`engine/metrics/resolver.py:39-42`).
  **[deferred → A3]**
- **The release/regression machinery has never been exercised**:
  `docs/releases/` does not exist — no release record has ever been written —
  and regression clauses 2–3 **pass unconditionally** even when a prior record
  exists (`engine/evals/release.py:85-94`). A regression gate that cannot
  fail. **[silent]**
- **The two adversary-facing detectors are the weakest and both non-gating**:
  the retrieval mapper fails its own bars (recall@5 0.74 vs 0.90 bar,
  false-gap 0.079 vs 0.05 ceiling, true-gap recall 0.29 with no bar) and was
  demoted to non-blocking (`engine/evals/run.py:321-360`); the injection
  lexicon's **held-out recall is 0.50** (`evals/injection/recorded.json`) —
  overfit to its tuning half — reported but ungated.
- **No requirement-coverage *score*** — per-section coverage findings exist
  (`engine/validation/checks.py:63-130`) but no `requirement_coverage` metric
  aggregates them, despite 35 defined metrics in `config/metrics.json`.
  Cheapest win against the critique. **[silent]**
- Live evidence is thin: ~3 recorded live baseline runs ever (2026-08-14),
  7 intake packages where the spec asked for 15, all corpora synthetic.

### The scores the feedback gave, revised

| Category | Their score | This review | Why it moves |
|---|---|---|---|
| Workflow architecture | 9 | **8.5** | Real and layered, but freezing is convention+partial-hash, no Gate 3 on export |
| Human-in-the-loop design | 9.5 | **8.5** | Superb UX pattern; identity behind approvals is a typed name |
| State/artifact management | 8.5 | **8** | Atomic + schema-validated writes; read side unvalidated, `write_json` escape hatch, run-id mint fragility |
| RFP domain modeling | 8.5 | **7.5** | Slots/obligations/gaps strong; no staffing/pricing/credential entities |
| AI orchestration philosophy | 9 | **9** | Deserved — the RAG ban, trust frames, refuse-loudly, zero-spend discipline |
| Enterprise readiness | 6 | **4.5** | No auth, no encryption at rest, no tenancy enforcement, no timeout on live calls, one worker thread |
| Knowledge-management moat | 6.5 | **6.5** | Governance moat real (8+); retrieval/content-model moat absent (4) |
| Collaboration | 6 | **5.5** | 8/10 substrate, 3/10 surface; zero integrations |
| Evaluation/QA maturity | 6.5 | **6** | 8/10 plumbing and honesty; 0/10 measured output quality today |
| Product UX maturity | unknown | **3.5** | Disciplined demo-grade; ~15 of 50+ doors surfaced, no ARIA, no guest page |
| Overall foundation | 8 | **8** | Fair — the seams (auth, caller, PursuitDir, stage-order authority) make the lift tractable rather than a rewrite |

---

## 2. Consolidated findings register

Deduplicated across all six reviews. **P0** = cheap and indefensible to defer
(hours–days each; close now regardless of phase). **P1** = must close before
any multi-operator use or the A1 real-data gate. **P2** = the enterprise lift
(A5/A6 scope, weeks each). **P3** = product-scope decisions needing an owner
call and a work package.

### P0 — close now (each is hours-to-days, and several undermine the repo's own laws)

| # | Finding | Evidence | Tag |
|---|---|---|---|
| P0-1 | **No timeout on live API calls** — a hung socket wedges the single job worker for every pursuit indefinitely. The SDK accepts a timeout; this is a ~10-line fix nominally parked at A6. | `engine/llm/live.py:146-159`, deferral note at `live.py:22-25` | deferred → A6, but indefensible at that distance |
| P0-2 | **Frozen-brief hash never verified downstream; frozen files writable in place.** Verify the checkpoint's `frozen_sha256` at every frozen read; refuse `write_artifact` to `*.frozen.json` outside gates. | `strategy/gate.py:217` vs `draft.py:111`, `validate.py:89`; `pursuit.py:46-55` | silent |
| P0-3 | **Run-id mint counts directory entries** — deleting any middle run directory makes the next mint collide and `RunLogger` silently appends to the old run, merging two audit traces. Mint `max+1`, refuse to open an existing run.jsonl for a new run. | `engine/workspace/pursuit.py:92-96`, `runlog/writer.py:78-82` | silent |
| P0-4 | **No cross-process lock for CLI vs server on one workspace** — `serve.lock` covers server-vs-server only; `make slice` against a live workspace races run minting and artifact writes. | `server.py:64-77`; CLI takes no flock | silent |
| P0-5 | **Mid-gate crash convergence trap**: replay requires a byte-identical `(decision, actor, at)` triple, and the web layer mints a fresh `at` per request — a crash between brief stamp and checkpoint makes the gate unrecoverable via UI. Key convergence on (decision, actor). | `strategy/gate.py:148-171` + `server.py:101` | silent |
| P0-6 | **Non-atomic writes off the main path**: org store is plain `write_text` (corruption loses the buyer-identity mapping), run `config.json` unfsync'd, jobs journal unfsync'd — inconsistent with the repo's own crash-safety law. | `engine/workspace/orgs.py:63-68`, `writer.py:139-141`, `jobs.py:70-71` | silent |
| P0-7 | **No Host-header validation / security headers / CSRF token** — the unauthenticated read API (all pursuits, drafts, run logs) is reachable by a DNS-rebinding page despite the loopback bind. TrustedHostMiddleware + headers is hours of work. | `engine/web/server.py` (no middleware anywhere) | silent |
| P0-8 | **Unbounded uploads read fully into memory; xlsx parsed in-process with no decompression limits** (zip-bomb DoS of the single server process). | `server.py:231, 598-612` | silent |
| P0-9 | **Regression gates are decorative**: clauses 2–3 pass unconditionally; no release record has ever been written (`docs/releases/` absent). Implement prior-record compare and commit a first record. | `engine/evals/release.py:85-94` | silent |
| P0-10 | **Schema/code contract mismatches**: kb-card schema says retrieval prefers won outcomes — code never consults `outcome`; advisor doc claims a revision-history UI that doesn't exist. In a repo whose rule is "schema is the contract," these are bugs by its own definition. | `schemas/kb-card.schema.json` vs `retrieve.py:178-180`; `docs/advisor/review-and-revision.md` | silent |
| P0-11 | **Client-supplied `at` on gate decisions** — approvals are backdatable. Server-stamp in web mode; keep injection for tests only. | `server.py:101-102` | silent |
| P0-12 | **Supply-chain quick wins**: no `--require-hashes` on the lockfile, docker base image unpinned by digest, extraction container runs as root with the repo mounted read-write. | `requirements.lock`, `docker/extraction-gate.Dockerfile:18` | silent |
| P0-13 | **EventsLane id minting race** on routes outside `_mutate` (`evt_{len+1}`) — duplicate event ids corrupt the feedback record silently. | `engine/web/events.py:71`; `server.py:880, 1677` | silent |
| P0-14 | **No corrupt-file recovery runbook** — a torn JSONL last line raises with no documented repair; `annotate.py` conversely masks a corrupt artifact as absent. | `writer.py:39-42`, `validation/annotate.py:96` | silent |
| P0-15 | **Requirement-coverage score** — one resolver + registry entry over findings that already exist. The cheapest possible answer to the critique's headline demand. | `checks.py:63-130`, `config/metrics.json` | silent |

### P1 — before multi-operator use and before A1 opens real data

| # | Finding | Evidence | Tag |
|---|---|---|---|
| P1-1 | **Real authentication + RBAC.** Self-declared names authorize everything including Tier-1 waivers and KB merges into the firm corpus; sessions in-memory, never expire, no logout; the CLI reaches the restricted de-anonymization store with a self-asserted `--actor owner`. The `header`/SSO seam exists but is unproven against a real proxy; there is no role model beyond `kb-access.yaml`'s two-purpose table. | `engine/web/auth.py:40-50`, `server.py:1509, 583`, `engine/cli/kb.py:203-219` | deferred → A5 (auth); RBAC concept silent |
| P1-2 | **Encryption at rest — including the de-anonymization store.** Restricted provenance (the placeholder→real-name map) and retained raw client bytes are plaintext on the same disk as everything else. Not even written down as a deferral. | `engine/kb/provenance.py:117-137`, whole workspace | **silent** — must be a named A1 precondition |
| P1-3 | **Audit breadth + tamper evidence.** Ordinary operator actions (reads, uploads, exports, KB export) leave no security log; all logs are rewritable plaintext JSONL with no hash chaining, no retention policy, no external shipping; recorded artifact hashes are never re-verified by any integrity sweep. | `server.py` routes; `runlog/writer.py` | silent |
| P1-4 | **Anonymization depth.** Recall 1.00 is proven on 22 synthetic cases of 3 identifier types; the scan's universe is the model's own proposed identifier list; taxonomy expansion is an admitted `TODO(spec-gap)`. A1's gate should demand NER/second-model cross-check and an adversarial eval set. | `engine/kb/anonymize.py:1-27`, `evals/anonymization/` | deferred → A1 |
| P1-5 | **Injection posture**: held-out recall 0.50 and non-blocking; the revision-comment → revision-agent lane and file-metadata injection are untested. Trust frames are the real defense and deserve their own adversarial eval. | `evals/injection/recorded.json`, `engine/intake/screen.py` | deferred → P10, thin |
| P1-6 | **Mapper below its own bars** (recall@5 0.74/0.90, demoted to non-blocking) — the retrieval backbone is the single weakest measured number in the system. | `engine/evals/run.py:321-360` | deferred (owner-gated B41) |
| P1-7 | **Notification delivery.** The Notifier is an honest no-op; the ping inbox has no UI; an SME who never opens the workbench is unreachable. The seam is designed for SMTP/webhook — days of work once the owner picks a channel. | `engine/web/pings.py:223-229` | deferred → N4/G3 (owner homework) |
| P1-8 | **Read-side validation**: validate on `read_artifact`; register schemas for the three `write_json` record types (events, addenda, revision rounds). | `pursuit.py:57-69` | silent |
| P1-9 | **Handoff `pending-calls/` retains full prompts (client text) forever; no retention schedule exists anywhere** for logs, pursuits, or share-link records. | `engine/llm/handoff.py:1-14` | silent |
| P1-10 | **Static analysis**: no mypy/ruff/formatter in CI; ~40% of defs unannotated including the core seams (`run_drafting`, `advance` take untyped positional deps despite a `CallerFor` Protocol existing). Convention-only typing erodes with contributors. | `pyproject.toml`, `.github/workflows/check.yml` | silent |
| P1-11 | **Web test fragility**: real-thread polling with 180s timeouts, 40s–11min observed variance, failure cascades 409s through later tests. A synchronous job mode for tests removes the flake class. | `tests/web/conftest.py:33-43` | acknowledged in-code |

### P2 — the enterprise lift (A5/A6 scope; the honest 2–4 engineer-month core)

| # | Finding | Evidence |
|---|---|---|
| P2-1 | **Throughput**: one global worker thread serializes every pursuit in the firm; per-pursuit locks already exist, so per-pursuit workers are the tractable first step — but the run-id mint (P0-3) must land first. | `engine/web/jobs.py:62` |
| P2-2 | **Persistence seam integrity**: writes funnel through `PursuitDir`, but ~246 raw read/exists sites bypass it (server reads `plan.json` directly; driver stage-skips are path-existence checks). The A5 storage swap is a multi-week refactor, not a driver swap — funneling reads through the seam is cheap now, expensive later. | `server.py:1565-1572`, `driver.py:233-321` |
| P2-3 | **Observability as a service**: no application log (2 `logging` imports repo-wide), retries visible only on stderr, no health endpoint, no metrics export, no log rotation. The run-log is excellent forensics but nothing alerts. | `live.py:209-211` |
| P2-4 | **A formal Gate 3 on the validated-draft → submission transition**, using the proven `approve_*` skeleton — the highest-stakes exit currently rides refusal logic + an accept stamp. | `docs/graph/doors.md`, `docx.py:66-77` |
| P2-5 | **Frontend completion**: surface the ~35 missing doors (waiver, ping, share, export, write-back, revision diffs, effort, outcome); build the guest share page; ARIA/dialog semantics, focus management, poll error handling. The read models already exist server-side — this is rendering work. | `app.js` vs `docs/graph/doors.md` |
| P2-6 | **Tracked-changes deliverables**: word-level redline in UI and a tracked-changes DOCX export; consulting reviewers live in Word. The before/after pairs exist per revision round. | `server.py:1148-1197`, `engine/assembly/docx.py:116-161` |
| P2-7 | **KB scale + ranking**: snapshot-keyed card index cache (a day, removes the O(corpus) query cost), then embeddings/hybrid rank behind the declared seam once A1 gives a real corpus to calibrate against. | `store.py:141-145`, `rank.py:26-34` |
| P2-8 | **Extraction orchestration**: per-call jail is sound (900s timeout, 12GB ceiling); team-scale concurrent intake needs pooling/queueing and a non-root, digest-pinned, read-only-mount container. | `extraction/worker.py:26-27`, `docker/` |
| P2-9 | **Quality measurement program** (the A3/A4 arc, sequenced): commit the first release record → judge-calibration label set (50–100 human-scored section pairs) → live drafter-rubric and red-team-accuracy lanes → the historical-RFP head-to-head corpus. The harness patterns (`remeasure.py`/`rebaseline.py`) are ready; data acquisition is the long pole. | `engine/evals/release.py:95-96` |
| P2-10 | **SIEM export, retention schedule, DLP on the outbound live-prompt path** (full buyer text goes to the model API un-redacted when live — a confidentiality decision that should be explicit, documented, and contractual, not incidental). | `live.py:146-159` |

### P3 — product-scope decisions (owner call + work package each)

| # | Finding | Why it matters |
|---|---|---|
| P3-1 | **Deal-side commercial modeling** — pricing sections, bill-rate cards, margin arithmetic, staffing plans, resource availability. Consulting RFPs are won and lost here; today these are human-answered content gaps. **The one large gap with no documented deferral anywhere in this mirror — a breach of the repo's own rule 5.** Minimum first step: write the deferral down with a closer; minimum viable feature: a pricing-section slot type + governed rate-card structure. |
| P3-2 | **People/credential content model** — resume/bio `doc_kind`, person entities, certification expiry, reference-usage tracking. Staffing sections are mandatory in RFPs and bios go stale fastest. |
| P3-3 | **Integrations** — inbound intake seam first (drop-folder/email mirroring the Notifier pattern), then SharePoint/DMS and CRM pursuit metadata. Zero seams exist today. |
| P3-4 | **Win/loss backlabel loop** — implement `outcome_backlabel` (schema-only today) so a closed pursuit's outcome propagates onto the cards that fed it via the existing proposal lane; then let ranking consult outcome (or fix the schema text — P0-10). |
| P3-5 | **KB conflict detection** — cheapest first step: a steward health-check running the existing consistency machinery over fact-sheet atoms and near-neighbor corpus pairs (the dedup machinery already finds neighbors), emitting proposals. |
| P3-6 | **Multi-approver policy** — "who may approve Gate 2," second-approver/partner sign-off, delegation. The system currently cannot express approval policy at all. |
| P3-7 | **Corpus freshness** — ingestion/outcome-date recency on corpus cards in curation and (post-calibration) ranking. |
| P3-8 | **Sentence-grain provenance** — citation grain stops at the section; the enterprise pitch implies finer. The A_designated wire path already carries per-answer kb_ids; prose needs span markers. |

### Minor findings and notes (M-series — on the record, below the register)

| # | Finding | Evidence |
|---|---|---|
| M-1 | No consolidated per-pursuit decision-log view — fully reconstructable but scattered across `runs/`, `checkpoints/`, `events/`, `addenda/` | pursuit directory layout |
| M-2 | Share-link secrets travel in the URL path (browser history, intermediary logs); web sessions never expire; no logout | `server.py:920-943`, `auth.py:36` |
| M-3 | Live evidence thin and aging: ~3 recorded live baseline runs (all 2026-08-14), 7 intake eval packages vs the 15 the spec asked for, KB validated only on the 60-card synthetic corpus; no re-baseline cadence | `evals/poison/history.jsonl` |
| M-4 | The extraction-gate eval runs only inside the Docker gate, not the offline CI suite — table-fidelity regressions invisible to a normal PR | `Makefile` gate targets |
| M-5 | `server.py` is a 1,823-line monolith with every route a closure inside `create_app` — unnavigable, routes untestable in isolation | `engine/web/server.py` |
| M-6 | Model pinning partial: only the Haiku id is date-pinned; other model ids float, so a provider-side update silently changes behavior under a "pinned" config digest | `config/models.yaml` |
| M-7 | No coverage tooling, property-based tests, or load/concurrency stress tests; the two-process races (P0-3/P0-4) have no tests because the design assumes them away | `pyproject.toml` |
| M-8 | B-number citations dangle in this public mirror — docstrings cite a decision register that doesn't ship; README flags it, but half the rationale trail is unreadable for adopters | README "Notes for adopters" |
| M-9 | Product notes: generated (non-template) render unbranded **[deferred → A6]**; advisor help agent has no UI tab and a ~95-line corpus; UI hardcodes every actor's role to `pursuit_lead`, mis-attributing effort-cost metrics by role | `app.js:246`, `docx.py:12-13` |

---

## 3. What the feedback missed entirely (both directions)

**Undervalued — real differentiators no score captured:**

- The **zero-spend/cost-governance discipline**: construction-gated live caller
  with price-staleness refusal, per-run ceilings, cross-run budgets, runaway
  call-count guard, fallback billed at fallback rates by config law
  (`engine/llm/live.py:109-132`, `caller.py:102-137`).
- The **tripwire** — scans every tracked file with no suffix allowlist,
  extracts committed binaries, scans full git history and commit metadata,
  fails loudly when its token list is missing, and tests that its own history
  scan can actually fail. Stronger than most commercial leak scanners.
- **Machine-verified documentation** — doors/modules/artifact-flow docs diffed
  against the live route table, Makefile, and argparse tree, two-directionally.
- **Refusal-lane honesty as a product feature**: refused ≠ error everywhere,
  absent-is-not-zero metrics, "unparseable judge output is a finding, never a
  pass," export refuses while packaging is blocked.
- The **buyer-form write-back and digest-verified template-fill** export lanes —
  buyer-native deliverables with a stream-diff verifier and honest
  `fill_by_hand` reporting — beyond what "early product" suggests.

**Overvalued — where the feedback was too generous:**

- It took the gate/freeze story at face value; the enforcement holes (P0-2,
  P0-5, P0-11) are invisible without reading the code.
- "Enterprise readiness 6/10" was generous: no authentication of any kind, no
  encryption at rest, no tenant enforcement beyond directory convention, one
  worker thread, and no live-call timeout is a 4–4.5 today. The mitigations —
  loopback bind, synthetic data, one trusted operator — are real but are
  exactly the conditions that end at A1/A5.
- It did not notice that **everything quality-shaped is unmeasured** — the
  eval score credited infrastructure that exists but has never produced a
  quality number, and a release act that has never been performed.

---

## 4. Cross-cutting themes

1. **The deferral register mostly works — and its breaches are therefore
   loud.** The overwhelming majority of gaps are written down with named
   closers (A1/A3/A4/A5/A6/N4/G15), exactly as CLAUDE.md rule 5 demands. The
   exceptions matter precisely because the rule is otherwise honored:
   encryption at rest (P1-2), deal-side commercial modeling (P3-1), the
   frozen-brief verification hole (P0-2), and the decorative regression gates
   (P0-9) are silent. Writing those four down — even before fixing them — is
   the fastest way to restore the register's integrity.
2. **"Deferred" has been doing double duty for "cheap but unscheduled."** A
   10-line API timeout parked at A6, atomic-write gaps in a repo whose law is
   atomic writes, Host-header validation — the P0 list exists because phase
   labels were absorbing work that costs hours. The production label the repo
   claims ("would I defend this once it holds a real client's material?")
   argues for closing all fifteen P0 items now.
3. **The backend is roughly two phases ahead of every surface.** Substrate
   8/10, UI 3/10, integrations 0/10. The next unit of product value is
   rendering and delivery (notifications, guest page, diffs, export buttons),
   not more pipeline.
4. **The system can currently prove it doesn't lie, but not that it writes
   winning responses.** Grounding/hallucination controls are code-enforced and
   real; every measure of quality is a stub awaiting A3/A4. That inversion —
   safety measured, quality unmeasured — is the right order to build in, and
   the wrong state to sell in.
5. **The seams are the asset.** Auth seam, `CallerFor` protocol, `PursuitDir`,
   the single stage-order authority, the Notifier stub, the embedding seam —
   the enterprise lift is tractable (est. 2–4 engineer-months to a defensible
   small-team deployment) *because* these exist. Protecting them (P2-2's
   read-path funneling especially) is cheap now and expensive later.
