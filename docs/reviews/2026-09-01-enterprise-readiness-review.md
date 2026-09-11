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

## 5. Session-34 internal sweep — addendum to the register (2026-09-01, B95)

*A second, independent pass over the canonical repo at `626522a` (suite 1446
green), run after this register was adopted. Method: the six P25 findings were
re-verified at their cited lines; then four scoped fresh-eyes sweeps ran — the
gate/freeze/run-log control plane and the test suite completed; the web/CLI/
assistant sweep and the parsers/LLM/mirror-tooling sweep were cut off by a
usage limit and were covered at spot-check depth only (limits in §5.4). Every
finding below was re-read at its cited lines before entry. Ids continue the
register's numbering; each has exactly one ROADMAP home (the B94 door).*

### 5.1 Confirmations

- **P0-5, P0-4, P0-3, P0-7, P0-2, P0-8 all hold at HEAD** — the cited lines are
  unchanged: `strategy/gate.py:148-152` still keys replay on the triple; no
  `flock` exists outside `web/server.py`; `pursuit.py:92-96` still mints
  `len+1`; no middleware or security header in `server.py`; `drafting/draft.py`
  and `validation/validate.py` read the frozen brief with no digest check
  against the checkpoint's `frozen_sha256`; `server.py:231` and `:598-612`
  write request bodies with no size cap, and every parser opens the whole
  workbook/document (`kb/xlsx.py:187`, `assembly/writeback.py:120`).
- **The B92 §2a coverage gap is exactly one path:** `spec/observability/
  RUN_LOG_DESIGN.md` is tracked but named by neither manifest nor deny list
  (799 tracked paths; 32 manifest entries, 27 deny entries; zero overlaps). It
  does not ship today only by implied exclusion — the case the coverage test
  is for. The ship/don't-ship call is the first thing that test forces.
- **Recorded after the first close (B96):** P2-14, P2-15 — surfaced by the test-integrity sub-report, missed at the first write, caught at the debrief.
- **Citation errata (session 35, B97):** P1-12's evidence cites `driver.py:696,703`; the file is 334 lines — the discarded research and win-themes returns are at `driver.py:245` and `:252`. The register's driver line ranges for P0-16 (`:289-292`, `:320-321`) are correct.
- **Solid, by reading:** `_atomic_write_json` (tmp + fsync + `os.replace`);
  every run-log line schema-validated, fsynced, seq under lock; frozen files
  written by exactly two sites and byte-equal by construction; draft→plan
  hash binding enforced at validation; the tripwire's non-vacuity discipline;
  the live caller's `RFP_LIVE=1` guard proven by a delete-detecting test
  (`tests/llm/test_live_caller.py:83`) plus the serve and slice seams; zero
  skips/xfails and no config-level exclusions beyond the roster-checked
  docling deselection; web tests upload the committed binary twins through
  the real parsers.

### 5.2 New findings

| # | Finding | Evidence | Home |
|---|---|---|---|
| P0-16 | **An addendum replan never voids the old draft on any path a user takes.** `addenda.py:17` promises "every existing draft voids by plan_sha256 mismatch", but the only verifier is `run_validation` (`validate.py:83-86`) and nothing re-invokes it: after re-approval the driver skips drafting because `draft.json` is `complete` (`driver.py:289-292`) and skips validation because the annotated file exists (`:320-321`); the submission export checks only `packaging.blocked` and owed pends (`assembly/docx.py:64-77`); the replan clears planning checkpoints but not drafting/validation (`addenda.py:137-143`). Scenario: buyer amends scope → firm replans and re-approves → advance says "nothing new" → export ships the pre-amendment response. `test_addenda.py:69` stops before re-approval. Register §1 calls the addendum lane "done right" — overstated. | `engine/web/addenda.py:17,137-143` · `engine/pipeline/driver.py:289-292,320-321` · `engine/assembly/docx.py:64-77` | **P25 item 8** |
| P0-17 | **Gate-2 mid-gate crash + `advance` silently discards the human's dispositions.** Write order is plan → freeze → log → checkpoint (`planning/gate.py:398-407`). A crash between the plan write and the freeze leaves an approved, stamped `plan.json` with no frozen copy; `advance` then enters planning (its predicate is the freeze's existence), `run_planning` has no past-gate guard (`plan.py:116-133`), and replay-always assembly rewrites `plan.json` from the pre-gate checkpoint as `gate2_pending` (`plan.py:201-213`) — kills, waives, dispositions and stamp gone, no error, while the run log carries an artifact line for the approved sha. P0-5 says "unrecoverable via UI"; the truth is "recoverable via advance, with silent loss". | `engine/planning/gate.py:398-407` · `engine/planning/plan.py:116-133,201-213` · `engine/pipeline/driver.py:264` | **P25 item 1** (rider on P0-5) |
| P1-12 | **`advance` while a pursuit awaits Gate 1 re-runs research and can mutate the brief under review.** The research block's only predicate is the frozen brief's absence (`driver.py:233-247`); `run_research` has no past-gate guard (`research/findings.py:142-160`) and `research_external` has no checkpoint — its "converges byte-identically" docstring is true only under `FakeCaller`; live or handoff, it is a second external call that replaces the findings. In the Gate-1 crash window it rewrites an already-approved brief, then the freeze copies the mutated content. The driver also ignores the research and win-themes stage returns (`driver.py:696,703`) while checking the other four. | `engine/pipeline/driver.py:233-247,696,703` · `engine/research/findings.py:11-17,142-160` | **P25 item 1** (rider on P0-5) |
| P1-13 | **Purge authorization is skipped when the lane is empty, and the accounting guard is dead.** `purge_org` authorizes through the restricted door only `if all_ids:` (`kb/purge.py:344-345`) and then `rmtree`s the org tree unconditionally (`:350`) — an org with zero memory cards is deleted with no access-gate call; `purge_pursuit_memory` has the same shape (`:280`). The three "accounting IS the deliverable" `RuntimeError`s (`:225,:299,:381`) can never fire: the ids are appended to the report in the same loop that iterates them, so the control reads as proven and proves nothing. No test asserts either. | `engine/kb/purge.py:225,280,299,344-350,381` | **P26** (rider; before real data) |
| P1-14 | **The revision round's "transactional commit (crash-convergent from the checkpoint)" is neither.** `round.py:376-546` writes archive (non-atomic `write_bytes`) → `draft.json` → annotated → finalize + `drop_pending` → round record → live plan. A crash after `draft.json` makes the next round refuse `stale_annotation` (`:90-93`), and a direct `run_validation` replays its completed checkpoint over the revised prose; a crash before `drop_pending` re-consumes the same comments; the round's checkpoint key is dead because `revision_n` already bumped (`:125-127`). No crash/resume test in `tests/revision/`. | `engine/revision/round.py:13-19,88-93,125-127,376-546` | **P26** (with P0-6) |
| P1-15 | **Rejection rationale is not in the audit record.** The run-log `gate` payload has no `notes` field (`schemas/run-log.schema.json`, `additionalProperties:false`); Gate-0 rejection stamps and checkpoints nothing (`intake/gate.py:262-273`), so the mandatory notes are discarded on receipt; Gate-2 rejection notes live only in `checkpoints/gate_2.json`, overwritten by the next decision. Tests require notes; none tests they survive. | `schemas/run-log.schema.json` gate block · `engine/intake/gate.py:262-273` · `engine/planning/gate.py:431-448` | **P26** (with P0-10) |
| P1-16 | **The live caller treats an internal exception as transient.** `live.py:200-202` classifies `status is None` as transient — a plain bug in `_request` (AttributeError, TypeError) is retried through the backoff ladder and then falls back to a second model: an internal defect becomes extra spend. Untested (`_status_error` always sets a code). Companion gap: the `RFP_LIVE=1` guard lives only on `LiveCaller.__init__`; no contract test forbids `import anthropic` outside `engine/llm/live.py`, so a second spend path added anywhere is caught by nothing. | `engine/llm/live.py:139-143,200-202` · `tests/contracts/test_graph_modules.py:158` | **P26** (with P0-1) |
| P1-17 | **A torn last line aborts run-log resume.** `read_run` (`runlog/writer.py:42`) json-loads every line; a crash mid-append leaves a truncated final line, and `RunLogger.__init__` (`:79`) raises `JSONDecodeError` straight out — the resume path a real crash produces is untested (`test_writer.py:71` dies only at a clean boundary). Also: `run_id` is interpolated into the path unvalidated (`:56`), bounded only by the mint. | `engine/runlog/writer.py:42,56,79` | **P26** (with P0-14) |
| P1-18 | **The public-cut orchestration guards are untested.** `tools/public_cut.py:173-176` (dirty tree), `:314-320` (overlay collision), `:325-328` (deny-in-staging), `:346-352` (engine imported from outside the tree), `:356-362` (suite must be green) are exercised only by live `make public-cut` runs; `tests/contracts/test_public_cut.py` covers the helpers and drift pins (strong) but never `_build_and_verify`/`main()` against a synthetic repo. Mirror safety is proven by the B90 dry-run, not by `make check`. | `tools/public_cut.py:173-176,314-362` · `tests/contracts/test_public_cut.py` | **P25 item 7** (rider: the guard pair's synthetic-repo harness proves these too) |
| P2-11 | Gate 0 emits `gap` lines and KB proposals (`intake/gate.py:154-169`) before the brief write (`:309`); a crash between replays them — duplicate gap lines inflate `totals.gaps_opened` and `propose_gap_answer_card` runs twice. | `engine/intake/gate.py:154-169,309` | **P25 item 1** (rider) |
| P2-12 | `RunLogger` accepts any `run_id` string in its path (`writer.py:56`); the invariant "ids come only from the mint" is asserted nowhere. | `engine/runlog/writer.py:56` | **P25 item 3** (rider on P0-3) |
| P2-13 | P0-5's triple-key convergence and client-`at` trap apply identically to gate_0 (`intake/gate.py:242-258`) and gate_2 (`planning/gate.py:333-360`); the register names only `strategy/gate.py`. | `engine/intake/gate.py:242-258` · `engine/planning/gate.py:333-360` | **P25 item 1** (scope: all three gates) |
| P2-14 | The handoff caller's response validation has type leaks: a non-dict payload, a missing/non-string `model`, a non-string `text` (`llm/handoff.py:147-166`) are untested, and a non-int `input_tokens` raises a bare `ValueError` from `int()` (`:172`) instead of a `HandoffError` refusal — in the pilot's own lane a hand-typed response file turns into a job traceback, not a refusal. | `engine/llm/handoff.py:147-172` | **P26** (with P1-16, the LLM boundary) |
| P2-15 | Nothing pins the live transport stub's shape against the installed SDK: every `LiveCaller` test injects a stub client (`tests/llm/test_live_caller.py:46`), `_get_client` (`live.py:139-143`) has zero coverage, and SDK attribute drift (`stop_reason`, `usage.cache_read_input_tokens`, `content[].type`) would pass the suite; `SpendBudget` counters (`caller.py:130-133`) have no lock — harmless under the single job worker, a race once P2-1's per-pursuit workers land. | `engine/llm/live.py:139-143` · `engine/llm/caller.py:130-133` | **P26** (shape pin, with P0-1) · **A5** (the lock, with P2-1) |
| P3-10 | **SharePoint as the end-user surface (owner question, 2026-09-01).** A5 names "Postgres/Blob behind the storage seams". Blob is the engine's system of record (machine-facing: atomic replace, locks, append-only logs, purge-by-deletion); SharePoint/OneDrive is where the firm's people already work. Recommendation on record: keep the workspace on Blob (or Azure Files); add SharePoint as an *integration seam* at A5 — buyer packages arrive from a document library, submissions land in one — via Graph, never as the workspace store. Named consequences: Graph throttling/latency, no lock or atomic-rename equivalent, and SharePoint's version history + recycle bin retain purged client material for months — the purge guarantee (R8) must extend to that tenant, which is an A1 data-governance question, not a UI one. | `ROADMAP.md` A5 row | **A5** — decided 2026-09-01 (B96): SharePoint enters as the integration seam, Blob stays the store; the A1 governance call stands for the day real client material transits the tenant |
| M-10 | Suite weak spots, none of which fake a result: order-coupled module fixtures in `tests/web/test_share.py:179` and `test_gates.py:164-166` (a setup 4xx would be masked); a conditional assertion at `test_gates.py:275-280`; `tests/llm/test_spend_budget.py:106` asserts source text (`inspect.getsource`) instead of behavior; `tests/runlog/test_run_totals.py:59-68` asserts `wall_ms >= 0`; `tests/kb/test_purge.py:39` uses `>=` on a deterministic fixture and `:101`'s comment claims more than its assertion; every `purge_client` test asserts a clean sweep (the dirty verdict is proven only in the lane variants). | as listed | **Opportunistic** — next touch of each file; the purge rows ride P1-13 |
| M-11 | `PursuitDir.__init__` materialises all eleven subdirs on every construction, read paths included (`workspace/pursuit.py:41-42`); `driver.py:243` copies the research pack with a non-atomic `write_bytes` (P0-6's class — rides P0-6). | `engine/workspace/pursuit.py:41-42` · `engine/pipeline/driver.py:243` | **Opportunistic** (mkdir) · **P26** (pack copy, with P0-6) |

### 5.3 Foundation verdict from the sweep

The primitives are sound and worth keeping: atomic single-file writes, a
validated append-only log, replay-always assembly from checkpoints, a real
hash binding from draft to frozen plan, a spend guard proven by deletion, a
tripwire that cannot pass vacuously. The one structural gap sits a level up
and repeats across P0-16, P0-17, P1-12 and P1-14: **there is no transaction
concept for multi-file transitions, and every skip predicate is a file-
existence or status check that never re-verifies the hash bindings the design
relies on.** The system converges only when identical inputs replay. That is
patchable in days inside the existing seams — verify bindings instead of
existence, refuse past-gate reruns, checkpoint the one unguarded external
call, key gate convergence on (decision, actor) at all three gates, land each
fix with a crash test at its exact write boundary — and does not warrant a
rebuild or a fork (B92 §3 stands). The honest caveat on "1446 green": it
proves the properties the suite *names*, over real files and real HTTP; it
does not name tamper-evidence of frozen files (P0-2), multi-file crash
convergence, or the public-cut orchestration (P1-18).

### 5.4 Coverage limits of this sweep (what was NOT reviewed)

- `engine/web/server.py` beyond the input-validation, upload, gate, and
  export doors (roughly half of its 72 routes unverified by reading);
  `engine/assistant/` beyond its tool catalog (read-only tools + proposal
  doors; the negative-surface test pins that it can never purge);
  `engine/cli/` beyond the command inventory.
- Parsers (`intake/`, `structure/`, `kb/ingest.py`, `assembly/`) beyond
  confirming whole-document loads (P0-8's case); XML-entity exposure in
  python-docx/openpyxl not assessed; `.github/workflows/` pins not re-read
  (P0-12 stands as written).
- Reopen trigger: **these two scopes get their fresh-eyes pass at the start
  of P25, before code** — their findings enter through the same door (id +
  home, same commit) and may re-order P25's items.

### 5.5 Session-35 step-0 sweeps — the two cut-off scopes, at full depth (2026-09-01, B97)

*The §5.4 reopen trigger, executed: two read-only agents (web/assistant/CLI;
parsers/assembly/CI) ran at P25 kickoff, before code, against `3e43d29`
(1447 green). Every line below was re-read by the session at its cited
site before entry; two agent items were duplicates of P1-13 and P0-8 and
were not entered. Ids continue the numbering; every id has exactly one
ROADMAP home (the B94 door). Coverage now complete for: all 72 `server.py`
routes (enumerated), `engine/assistant/`, `engine/cli/`, `engine/intake/`,
`engine/structure/`, `engine/kb/{ingest,read,xlsx,curation}.py`,
`engine/assembly/`, `.github/workflows/check.yml`.*

| # | Finding | Evidence | Home |
|---|---|---|---|
| P0-18 | **A share-link guest supplies the clock the expiry check uses** — `?at=` (and the comment payload's `at`) is caller-controlled, so an expired link is reusable forever and the access log records the guest's chosen timestamp. `tests/web/test_share.py:70-73` drives expiry through `?at=`: the test's mechanism is the bypass. | `engine/web/server.py:921-922,944-945` (`when = at or now()`) · `engine/web/share.py:119` | **P25 item 4** rider — guest routes ignore any caller `at`; tests inject through the app's `now` seam |
| P0-19 | **`GET /api/pursuits/{id}/review` serves the FULL internal review model unauthenticated** — pending internal comments, waiver identities, red-team findings — while the guest route strips exactly those server-side (`state.py:150-153`). The guest split is defeated at the door. | `engine/web/server.py:1093-1096` (no `Depends(operator)`, no `include_internal=False`) | **P25 item 4** rider — operator dependency on the internal review surface |
| P0-20 | **The packaging block is enforced on ONE exit door only.** `render_submission` refuses under `packaging.blocked`/owed pends; the three write-back lanes — including `template_fill`, whose output IS `exports/submission/response.docx` for a firm-default pursuit — check neither, and the writeback confirm door runs all three. A blocked response ships through the lane the pilot demonstrates. | `engine/assembly/docx.py:63-77` vs `template_fill.py:273-290` (`OUTPUT_NAME = "exports/submission/response.docx"`), `writeback.py:151-165`, `docx_writeback.py:218`; `server.py:799-805` `_run_one` | **P25 item 8** rider — one `assert_current` at both exit doors carries the block/pends refusal for every buyer-facing lane |
| P1-19 | xlsx write-back re-saves the buyer's workbook through openpyxl with no post-write round-trip proof (its docx twin has `_assert_roundtrip`); openpyxl drops images, charts and cached formula values on load/save — the buyer's form comes back with content silently missing. | `engine/assembly/writeback.py:160-165` | **P26** rider (part-inventory round-trip assert; refuse on drift) |
| P1-20 | `event_id` is minted `len(read())+1` with no lock, and three mutating event routes (`add_event`, `record_outcome`, `record_effort`) take no `_mutate` — two concurrent appends mint the same id into an append-only record, and an outcome/effort can interleave with a revise job finalizing events. | `engine/web/events.py:73` · `engine/web/server.py:1622,1677,1691` | **P25 item 3** rider (count-derived ids under the pursuit guard; the three routes take `_mutate`) |
| P1-21 | `merge_batch` is not atomic: a mid-batch refusal leaves earlier cards rewritten and marked `accepted`, and the curation-log line — the record of what changed — is written only after the loop. The route turns it into a 409 that hides the partial apply. | `engine/kb/curation.py:329-352` · `server.py:583` | **P26** rider (validate the whole batch, then apply; log what was applied on any exit) |
| P1-22 | The same `len()+1`/read-modify-write class elsewhere: share `link_id` (`sl_NN`) minted without a lock and `create_share` takes no `_mutate` (two creates fold into one, orphaning a token); `org_id` minted by scan with no lock; `inbox/roles.json` read-modify-write outside `_mutate`. | `engine/web/share.py:85` + `server.py:880` · `engine/workspace/orgs.py:77-81` · `server.py:238-243` | **P25 item 3** rider (with P1-20) |
| P1-23 | The workbook and docx structure parsers have no warnings channel: `ParsedWorkbook` carries no `warnings`; every row that falls through classification is dropped with zero record (`# Everything else: furniture.`); pre-filled answer rows are skipped silently. The P10-F16 class (lessons.md line 19). | `engine/structure/parse.py:28-40` · `classify.py:326` · `docx_buyer.py:118-122` | **P26** rider — parser fidelity group |
| P1-24 | A buyer question authored as a formula (`='Instructions'!A5`, common) produces NO slot and NO warning: formula cells are excluded from slot text and `data_only=False` reads no cached value. | `engine/structure/facts.py:81` · `classify.py:222` | **P26** rider — parser fidelity group |
| P1-25 | Intake renders formula SOURCE text into the brief and the model prompt unwarned (`=B2&" "&C2` where the human sees a date); the KB import lane refuses formula cells by name for exactly this reason, intake does not. Formula evaluation is correctly absent. | `engine/intake/extract.py:88` vs `engine/kb/xlsx.py:145-149` | **P26** rider — parser fidelity group |
| P1-26 | Hidden-content marking is narrower than the stated contract: hidden sheets and rows are marked, hidden COLUMNS are extracted unmarked (`column_dimensions` never consulted) and cannot fire the `hidden_content` flag; the module docstring says "hidden workbook content is extracted AND marked" — a stated property stronger than the implemented one (lessons.md line 11). Unsure, same class: docx `w:vanish` hidden text. | `engine/intake/extract.py:11,94,112` (0 hits for `column_dimensions`) | **P26** rider — parser fidelity group; **the docstring is corrected in P25 item 6's commit** (the file is touched there) |
| P1-27 | Firm-template authoring scaffolding ships to the buyer: `template_fill` strips only the guidance boxes of filled sections; the "How to Use This Template" front matter, its `Field` table and every `[ Replace with the drafted section. ]` placeholder of an unfilled section survive into `exports/submission/response.docx`; `remaining_guidance` does not list the front matter and nothing blocks the download. | `engine/structure/docx_default.py:76-161` (front matter skipped by the parser, so the fill never sees it) · `engine/assembly/template_fill.py:169,273` | **P26a item 1** — pulled forward (the owner's call, 2026-09-02, B99); ships as the next work-side tag |
| P2-16 | The download door serves `root / entry["path"]` straight from the on-disk bundle record with no containment re-check; `output_name` is engine-derived today, so unreachable — but the door verifies nothing about the record it trusts. | `engine/web/server.py:751-754` | **P25 item 4** rider (one `is_relative_to` line) |
| P2-17 | `PURSUIT_ID` is applied only at creation; every other route joins `pursuit_id` into `workspace / pursuit_id` unvalidated — `_pursuit_root("..")` passes `is_dir()` and the following `PursuitDir(workspace, "..")` mkdirs eleven subdirectories in the workspace's PARENT. | `engine/web/server.py:103-107` · `engine/workspace/pursuit.py:40-42` | **P25 item 4** rider (validate in `_pursuit_root`, 422) |
| P2-18 | The waiver door writes `run_end(status="completed")` before checking the result — a refused waiver gets a mini-run footer claiming success; `approve_waiver` is also uncaught. | `engine/web/server.py:1525-1535` | **P25 item 4** rider |
| P2-19 | Schema violations on the four event doors surface as 500s: `EventsLane.append` raises `ContractError`, the routes catch only `EventsError` (sibling `ValueError` subclasses). | `engine/web/events.py:41,78` · `server.py:986,1002,1013,1244,1593` | **P25 item 4** rider |
| P2-20 | A crashed job leaves a footerless run that the runs read model reports as `in_flight` forever, disagreeing with the job journal's `error`; nothing reconciles the two records. | `engine/web/jobs.py:157-162` · `server.py:152-156` | **P26** rider (with P0-14/P1-17, the run-log recovery group) |
| P2-21 | `engine slice --fresh` `rmtree`s whatever `--workspace` names — no confirmation, no path sanity: `--workspace ~` deletes it. | `engine/cli/slice.py:260-261` | **P25 item 2** rider (refuse unless under the pursuits root and carrying a workspace marker) |
| P2-22 | `kb purge` is destructive with a self-asserted actor: authorization goes through the restricted door, but `--actor` is free text, so anyone with shell access types an authorized name. Honor-system until A5's SSO reaches the CLI. | `engine/cli/kb.py:112-114,202-203` · `engine/kb/provenance.py:82` | **A5** (auth) — SECURITY.md states the declared-actor posture now (this commit) |
| P2-23 | `kb_id` and `proposal_id` reach path construction unvalidated from JSON payloads; existence checks bound reads, but an accepted proposal WRITES to the resolved path; `proposal_ids` elements are not type-checked (`TypeError` 500). | `engine/kb/store.py:87-88` · `engine/flywheel/proposals.py:40-41` · `server.py:549,585` | **P26** rider (id regexes at the store boundary) |
| P2-24 | Prompt-frame delimiters are not escaped in the assistant loop: card/doc content containing the retrieved-frame closing tag or a `\n\n[USER n]` line start forges a frame; the injection screen and the frame are tested, the delimiter is not. Content is firm-authored and steward-gated. | `engine/assistant/loop.py:80-93` · `engine/assistant/frames.py:41-44` | **A4** (with P1-5, the injection posture eval) |
| P2-25 | openpyxl parses worksheet bodies with stdlib `iterparse` and `defusedxml` is not installed, so INTERNAL entity expansion is live (billion-laughs) — a small, low-ratio xlsx blows memory; distinct from the size/zip-ratio caps. External entities are off on both lanes (verified). | `.venv/…/openpyxl/xml/functions.py:40-42` (`DEFUSEDXML False`) · `requirements.lock` (absent) | **P25 item 6** rider (add `defusedxml` to the lock — openpyxl switches parsers with no code change) |
| P2-26 | `pypdf` runs at `strict=False` with its warnings on the `pypdf` logger that nothing captures; a partially-recovered PDF looks identical to a clean one in the run log. | `engine/intake/extract.py:126-129` | **P26** rider — parser fidelity group |
| P2-27 | Body-only docx walks: headers, footers and text boxes are never read by intake extraction, buyer-docx structure parsing, or KB ingestion — buyer instructions in a header are absent from the brief, the slots and the injection screen's input. | `engine/intake/extract.py:138-147` · `engine/structure/docx_buyer.py:99` · `engine/kb/read.py` | **P26** rider — parser fidelity group |
| P2-28 | CI: `pull_request` from a same-repo branch runs PR-authored `Makefile`/tests with `secrets.TRIPWIRE_TOKENS` on disk (per-line masking covers verbatim echoes only); `setup-uv` `enable-cache: true` on PR runs lets a branch seed the cache `main` restores; `actions/checkout` keeps `persist-credentials` at its default. Bounded: the private repo has no forks and `permissions: contents: read`. Pins themselves are sound (full SHAs, version comments, no `pull_request_target`). | `.github/workflows/check.yml` | **Opportunistic, next CI touch** (with the Node 20→24 pin bump — long-lead) |
| P2-29 | A control character in prose (reachable from buyer text through the drafting lane) makes python-docx raise `ValueError`, which neither exit door catches — the request 500s and the gate run is left without a footer. Verified: `add_paragraph("bad\x0bchar")` raises. | `engine/assembly/docx_writeback.py:230` · `template_fill.py` `add_paragraph` · `server.py:713-716,846-865` | **P25 item 8** rider (both doors close the run on ANY exception) · **P26** (typed refusal of control characters at the envelope boundary) |
| P2-30 | Ragged buyer tables crash instead of refusing: `row.cells[answer_col]` and `row[i]` index by the header width, an OOXML row with fewer cells raises `IndexError` untyped past `parse_buyer_docx`. | `engine/structure/docx_buyer.py:118-122` and the grid/fill-in helpers | **P26** rider — parser fidelity group |
| P3-11 | `AuthSeam._sessions` is an unbounded in-memory dict fed by an unauthenticated POST — any local client mints sessions indefinitely, each with an arbitrary 2–60-char operator name that lands in gate actor and `waived_by` fields. | `engine/web/auth.py:36,48-49` · `server.py:114` | **A5** (auth rework, with M-2) |
| P3-12 | Share tokens are compared with `==` (non-constant-time) and `expires_at` has no upper bound. | `engine/web/share.py:110,80-81` | **P25 item 4** rider (`compare_digest`; cap at now+30d) |
| P3-13 | Payload fields are read with `.get()` and no type check across the route surface — a wrong-typed field is a 500, not a 422 (`dict(effort)` on a string; `PURSUIT_ID.match` on a non-str). | `engine/web/server.py:1236-1237,175` | **P26** rider (with P2-14, the type-leak class); the post-commit `effort` case closes with P25 item 1's validate-before-decision |
| P3-14 | A guest's `slot_id` is passed into the pending record unvalidated (only `section_id` is checked against the plan), so a guest comment can be tagged to a foreign slot a later revision round targets. | `engine/web/server.py:963,982` | **P26** rider |
| P3-15 | Output documents carry the generator's identity and pass through source metadata: nothing sets `core_properties`; the bundled template's `docProps/core.xml` names python-docx as creator; tracked changes and comments in a real firm template would round-trip unflagged (both verifiers compare text/style only). | `config/templates/firm-default-template.docx` `docProps/core.xml` · 0 hits for `core_properties` in `engine/` | **P26** rider (metadata hygiene on every buyer-facing output) |
| M-12 | `plan_import`'s `unchanged` count subtracts errors from rows; a row can produce several errors, so the number a steward reads can understate or go negative. | `engine/kb/xlsx.py:318` | **Opportunistic** — next touch of the file |
| M-13 | A non-ISO guest `at` raises an uncaught `ValueError` (500) on the unauthenticated share routes — moot once P0-18 removes caller-supplied clocks. | `engine/web/share.py:34-35` | **Closed by P0-18** (P25 item 4) |

**Verified sound at full depth (no finding):** the job lane's check→guard→re-check and typed error lanes; share-token secrecy and the revoke kill switch; the one guest write door (screened, pending, `external` provenance); server-derived `revision` on events; the assistant's 14-tool catalog (12 reads, 2 proposals, zero writers), strict per-tool argument schemas, bounded results and a triple-bounded loop, citation gate, session-id-as-traversal-guard, derived spend under a preflighted ceiling, lane unmixability; every assistant route operator-gated; no shell injection anywhere (list-form subprocess only); `serve` host not an argument; the evals rebaseline arm triple-gated; XXE off on both XML lanes (python-docx `resolve_entities=False`; openpyxl `fromstring` hardened) and no engine code parses document XML directly; no parser follows external references; formulas never evaluated; all buyer text inside the untrusted frame; one injection-screen registry over the full text including hidden segments; encrypted/unparseable documents refuse loudly before spend; model output whitelisted; docx write-back and template fill prove their change sets; no buyer string can reach a docx field or attribute unescaped; write-back digest- and plan-bound; downloads record-gated; honesty rules clean (no test-only branch, env switch or hard-coded success path in the swept modules); workflow pins are full SHAs with version comments, `permissions: contents: read`, no `pull_request_target`.

**Still unreviewed by any pass (named, with its trigger):** `engine/extraction/` beyond the sandbox seam (the docling lane), `engine/evals/`, `engine/metrics/`, `engine/flywheel/` beyond `proposals.py`, `engine/kb/` beyond ingest/read/xlsx/curation/purge, `engine/web/state.py` and `pings.py` beyond their read paths. Trigger: **P26 kickoff** — one sweep, two agents at a time, same door.

### 5.6 P25 closure (2026-09-02, B98)

Closed by P25, each with a named test in the suite: **P0-2** (`read_frozen`
+ the freeze door; `tests/workspace/test_pursuit.py`, `tests/planning/
test_plan_refusals.py`, `tests/web/test_export.py`) · **P0-3, P2-12**
(`tests/workspace/test_run_mint.py`, `tests/runlog/test_run_id_guard.py`) ·
**P0-4, P2-21** (`tests/workspace/test_workspace_lock.py`, `tests/cli/
test_cli_lock.py`) · **P0-5, P2-13, P0-17, P1-12, P2-11** (`tests/contracts/
test_gate_key.py`, the three gate test files, `tests/pipeline/test_driver.py`,
`tests/research/test_research_resume.py`, `tests/web/test_gates.py`) ·
**P0-7, P0-18, P0-19, P2-16, P2-17, P2-18, P2-19, P3-12, M-13** (`tests/web/
test_security_headers.py`, `test_share.py`, `test_gates.py`,
`test_foundation.py`) · **P0-8, P2-25** (`tests/web/test_upload_caps.py`,
`tests/intake/test_zipguard.py`) · **P0-16, P0-20, P2-29a** (`tests/pipeline/
test_driver.py`, `tests/drafting/test_draft_resume.py`, `tests/web/
test_export.py`, `tests/web/test_addenda.py`) · **P1-18** + the B92 guard pair (four of five guards proven at P25; the import-provenance probe P3-16 driven to its refusal by P29a)
(`tests/contracts/test_public_cut.py`, `test_public_cut_orchestration.py`) ·
**P1-20, P1-22** (`tests/web/test_events.py`, `test_share.py`,
`test_org_routes.py`) · **P1-26** (docstring half; the hidden-column marking
itself stays in P26). Ids remain permanent labels; nothing here renumbers.

### 5.7 Session-36 step-0 sweeps — the never-reviewed modules (2026-09-02, B104)

*The §5.5 coverage list's remainder, executed at P26a kickoff after item 1
shipped: two read-only agents (extraction beyond the sandbox, evals,
metrics; flywheel beyond proposals, kb beyond ingest/read/xlsx/curation/
purge, `web/state.py` + `pings.py` in full) ran against `0f10fb4`. Every
line below was re-read by the session at its cited site before entry.
Ids continue the numbering (P1-28 and P2-31 were minted by B101/B103
mid-slice); every id has exactly one ROADMAP home (the B94 door).
Coverage is now complete for every package under `engine/`.*

**Planning errata (register citations that moved or half-closed since
2026-09-01, each re-read at the new line):** `live.py:22-24` (was 22-25) ·
`server.py:109-110` `_at` (was 101-102) · `orgs.py:64-69` · `writer.py:156-159`
(run config) · `driver.py:265-267` (pack copy) · `pursuit.py:76-77` (M-11
mkdir) · `round.py:91-95` / `:127-129` / `:377-548` · `events.py:90` (id
mint, under `_APPEND_LOCK` since P25) · `server.py:880` / `:1677` (both now
inside `_mutate` / read-only) · `test_graph_modules.py:158` (blank; nearest
test :159). **P0-9**: "`docs/releases/` absent" is the public MIRROR's view
(`deny.txt:15`); four records are tracked in v2 — the real defect is that
clauses 2–3 emit `pass` on BOTH branches of `if prior is None`
(`release.py:85-94`), `load_record` has zero callers and is version-keyed,
`overrides` is always `[]`, and a clause failure would not change the exit
code. **P2-14**: the three type guards exist (`handoff.py:146,155,165`); the
defects were the two bare `int()`s (closed, B101). **P1-14**: the
`run_validation` replay claim is obsolete (P25 item 8 bound its checkpoint);
the live defects are the re-keyed round checkpoint, the never-cleared
checkpoint, and the un-deduped finalize — closed by P26a; the commit
resumed, but its RECORD was empty (or misattributed to the previous
round) whenever the crash fell between `drop_pending` and the record
write, until P1-53 (P29b b5, B133: the record's inputs are checkpointed
before the drop and read back on resume). **P1-17**: the `run_id` half
closed by P25 item 3; the torn-tail half has four faces (resume, two routes,
the board) plus the jobs journal — which tolerated a torn tail on READ and
corrupted it on WRITE until P1-51/P3-20 (P29b b1, B133: the one tail rule in
`append_fsync`, every appender routed through it). **P3-13**: the `effort` half closed by
P25 item 1; the `PURSUIT_ID.match` half closed by B101. **P0-13**: landed
by P25 item 3's riders; the residual gap (`revoke_share` outside `_mutate`)
was closed under `_mutate` at B104 §5 and re-opened as P2-58 — revoke is
serialized by the share lane's own lock and job-blocked by nothing (P29b b2,
B133); the events and share lanes' torn-tail fold is P2-57's, same commit.

| # | Finding | Evidence | Home |
|---|---|---|---|
| P0-21 | **The guest share view leaks the waiving operator's identity.** `_claim_mark` builds `line = f"waived by {waived_by}: …"` before the guest strip, which removes `waived_by` from `detail` only; `waiver_reason` is not stripped either. `docs/advisor/share-links.md` promises the opposite; `test_share.py:122` asserts the KEY name, on a fixture with no waiver. | `engine/web/state.py:130-133,180-182` | **P26a Group D** rider (with P0-11) |
| P1-29 | A malformed docker worker result (`IndexError` on empty stdout, `JSONDecodeError` on a trailing line, `ValueError` from `from_dict`, `TimeoutExpired`) escapes `convert` uncaught — the whole intake job dies instead of one document degrading through the `ExtractionFailed` lane. | `engine/extraction/backend.py:105-117` · `engine/intake/extract.py:310` | **P26b** (parser fidelity) |
| P1-30 | The two-path fabrication tripwire iterates deterministic grids only and is gated on `doc.grids` — a table the deterministic path DROPPED is never diffed. | `engine/extraction/twopath.py:24-28` · `engine/intake/brief.py:417` | **A1 (§A2 rerun)** |
| P1-31 | The §A2 gate excludes timed-out documents from the p95 denominator and reads neither `failure_behavior` nor the reading-order/OCR measures in `evaluate_kill_criteria` — a timeout flatters throughput and no criterion notices. | `engine/extraction/gate.py:369-373,499,142-207` | **A1 (§A2 rerun)** |
| P1-32 | `production_only` keys run headers by `run_id`, which is unique only WITHIN a pursuit — across the flattened corpus `run_0001` collides, last pursuit wins, and a bench run in one pursuit silently drops (or admits) another pursuit's production records. The metrics fixture has one pursuit. | `engine/metrics/walker.py:109-112` · `engine/metrics/resolver.py:73` | **P26a Group E** rider (with P0-15) |
| P1-33 | `extraction_fabrication_count` reads `two_path.tables_diffed` on a FILENAME-keyed dict the writer produces — the critical-alert metric can never fire; it renders as "absent". | `engine/metrics/resolver.py:412-413` · `engine/intake/brief.py:432,446,460` | **P26a Group E** rider |
| P1-34 | `injection_screen_flags` counts every screen line (`pass` and `flag`) — the registry's "zero forever means the screen is dead" liveness signal is destroyed — and is the one resolver returning `0.0` on an empty corpus against the module's absent-is-not-zero law. | `engine/metrics/resolver.py:341-345` · `engine/intake/brief.py:401-404` | **P26a Group E** rider |
| P1-35 | The board's stage and the review model still decide on artifact EXISTENCE while the driver decides on hash bindings (P25 item 8): after a replan the board says `review` / `validated` over an annotation bound to a plan that no longer exists. The docstring claims parity with the driver. | `engine/web/state.py:58-59,81-89,116-118,194-198` | **P26a Group C** rider (with P2-20) |
| P1-36 | A ping answer's TEXT lives only in the mutable plan/brief, written by the caller AFTER the journal line; a failure between the two loses the SME's answer and the ping refuses to be answered again. | `engine/web/pings.py:125-127,138-142` · `server.py:1165` | **P26a Group C** rider (with P0-14) |
| P1-37 | Re-ingest stops being idempotent after a drift: the drifted card keeps the OLD id, its new content hash is recorded nowhere the matcher looks, so the same unchanged bytes re-classify as drifted (drift 0.0) on every later ingest — version bumps, snapshot moves, a false `reconciliation: flag`. v1→v2→v2 is untested. | `engine/kb/ingest.py:513-522,528,620-622` · `tests/kb/test_reingest.py:69,87` | **P26b** (KB curation) |
| P1-38 | Two reconciliations of the same source bytes against different priors write the SAME report path (`doc_id-canonical_doc_id`), the second erasing the first's drift record. | `engine/kb/reconcile.py:129-139` | **P26b** |
| P1-39 | `ProposalStore.decide` has no state machine: an accepted proposal can be re-decided `rejected` from the reject route, replacing the `decided` block wholesale while the curation log still records the merge. The docstring claims "nothing is deleted". | `engine/flywheel/proposals.py:85-91` · `server.py:596-598` | **P26b** (with P1-13) |
| P1-40 | The firm KB has no mutual exclusion: `merge_batch`'s "a decision is made once" is check-then-act and the KB routes take no guard (`_mutate` is per-pursuit), so two stewards interleave and both curation-log snapshot pairs lie. Distinct from P1-21 (atomicity within one batch). | `engine/kb/curation.py:328-344` · `server.py:583-613` | **P26b** (with P1-21) |
| P1-41 | The flywheel is a library nothing calls: `write_card_signals` and `route_edits` have zero engine call sites, so no card ever gains `edit_survival` (the retrieval tie-break can never fire), no edit is ever routed, and `lesson_to_draft_lag_days` can only be absent. Metrics are honestly absent, not falsely zero. | `engine/flywheel/survival.py:79,7-8` · `routing.py:79` · `server.py` `accept_pursuit` | **P26b** (the flywheel wiring at accept; A4 calibrates it) |
| P2-32 | `_bar_misses`: a missing measure passes a ceiling (`_max`) bar and fails a floor bar — dropping a key behind `false_gap_rate_max` silently clears it. | `engine/evals/release.py:31,43` | **P26a Group E** rider (with P0-9) |
| P2-33 | A lane carrying any `status` is never scored against its own bars (`misses = [entry["status"]]`); latent today (only `baseline_stale`/`not_measured_live` reach it). | `engine/evals/release.py:57-63` | **P26a Group E** rider (with P0-9) |
| P2-34 | `write_record` clobbers `docs/releases/<version>/eval-results.json` in place with no archive — the rebaseline history discipline is absent for release records. | `engine/evals/release.py:148,157-163` | **P26a Group E** rider (with P0-9) |
| P2-35 | The four fingerprint locks prove the environment, never the number: `check_baseline` compares fingerprints stored beside the measures in the same file; an edited recall clears a blocking bar. Commit review is the only control. | `engine/evals/claim_extraction.py:216-243` · `rebaseline.py:164` | **P26b** (eval integrity before A1's re-baseline) |
| P2-36 | Every eval-lane rate returns a vacuous 1.0/0.0 on an empty denominator and no lane declares a minimum n — a cases file that stops marking any case `must_flag` re-baselines to a perfect number. | `engine/evals/claim_extraction.py:156-159` · `mapper.py:97-101` · `voice.py:67` · `intake.py:85,91` · `structure.py:141` · `trajectory.py:145` · `consistency.py:110` | **P26b** |
| P2-37 | `remeasure`'s "live" is a self-declared keyword (nothing checks `RFP_LIVE` or the caller), and its `RECORDED_BASELINE` is a hand-typed copy with no drift pin. | `engine/evals/remeasure.py:39-43,82-94` | **P26b** |
| P2-38 | The sandbox child's result-file write sits outside its try/except and is not atomic — a non-serializable value leaves a truncated but EXISTING result the parent json-loads into an uncaught error, the original lost. | `engine/extraction/_child.py:66-77` | **A1 (§A2 rerun)** |
| P2-39 | The in-process sandbox's network denial patches `connect`/`getaddrinfo` but not `sendto`/`sendmsg` (UDP, DNS to a literal IP); the docker lane's `--network none` is the outer wall. | `engine/extraction/_child.py:30-33` | **A5** (with the container lane) |
| P2-40 | `_docker_ready` probes the daemon with no timeout — an unresponsive daemon hangs `resolve_backend()` and wedges the job worker before any conversion (P0-1's class, second site). | `engine/extraction/backend.py:64-67` | **A1 (§A2 rerun)** |
| P2-41 | A `docker run` timeout kills the CLI, not the container — orphans accumulate with their 12 GB ceiling and mounts. | `engine/extraction/backend.py:105-109` | **A1 (§A2 rerun)** |
| P2-42 | `cycle_time_days` sums engine `wall_ms` and divides by pursuits — the registry's formula is `submission_date − receipt_date` over `run_log` AND `crm`, and `crm` is in `UNSOURCED_STREAMS`; every other crm-sourced metric is honestly unsourced, this one returns a plausible number. `submission_volume` is the weaker sibling. | `engine/metrics/resolver.py:376-389,39-42,477-478` | **P26a Group E** rider |
| P2-43 | Two bench-view absences report the wrong reason: `_r_false_gap_rate` sets no `absent_reason` (generic text), `eval_pass_state`'s slot still says "lands later in P10". | `engine/metrics/resolver.py:369-373,491,546-547` · `views.py:74-76` | **P26a Group E** rider (with P0-9) |
| P2-44 | `PursuitRecords.torn_lines` is recorded and read by nobody — a torn `run_end` drops that run's totals from every totals metric with no reader ("recorded, never silent" has no surface). | `engine/metrics/walker.py:49,76` · `resolver.py:64-91` · `views.py:83-89` | **P26a Group C** rider (with P1-17) |
| P2-45 | `text_survival` leaves `SequenceMatcher`'s autojunk on: past 200 characters the score is length- and repetition-dependent (measured: one changed word in a 1,550-char section scores 0.80), so cross-section averages compare incomparable numbers; the suite's fixture is 156 chars. | `engine/flywheel/survival.py:38` · `tests/flywheel/test_survival.py:20` | **P26b** (with P1-41) |
| P2-46 | The restricted store's L0 read doors (`source_meta`, `source_exists`, `list_source_ids`, `absorbed_owner`) and `reconcile.prior_models` bypass the access log and authorization the module's own law states; `source_meta` carries the real `source_client`. No route exposes it. | `engine/kb/provenance.py:5-8,132-148,195-203` · `reconcile.py:70-71` · `ingest.py:448-454` | **P26b** (with P1-13) |
| P2-47 | Ping escalation runs on a caller-supplied clock on both read routes (`?at=`) and on the record itself (`pinged_at` from the payload) — P0-18's principle unapplied to this lane, P0-11's backdating on the escalation record. | `engine/web/server.py:1198-1206,109-110` · `pings.py:211-218` | **P26a Group D** rider (with P0-11) |
| P2-48 | The server clock is NAIVE (`strftime` without `Z`) while `_parse` accepts the `Z` form — one legal `POST …/ping {"at": "…Z"}` stamps an aware `pinged_at` and every later `GET /api/pings` (naive clock) 500s for EVERY pursuit, with no repair door on an append-only record. The suite's `FIXED_AT` is naive, so the aware branch is never exercised. | `engine/web/pings.py:32-33,211` · `server.py:59-60` | **P26a Group D** rider (with P0-11 — the server-stamped clock removes the client input; `_parse` normalizes) |
| P2-49 | One corrupt file in one pursuit (torn `brief.json`, torn run-log line) 500s the whole board — `_read_json`/`read_run` raise straight out of `board()`. | `engine/web/state.py:24-27,36,100-101` | **P26a Group C** rider (with P1-17) |
| P2-50 | `infer_edit_reason` compares the SET of digit characters — 1,200→2,100, 2024→2042, 12→21 read as "no number changed" and route nowhere. | `engine/flywheel/routing.py:51,59,63` | **P26b** (with P1-41) |
| M-14 | `gate.py:385` aliases one dict into both slots of `_empty` (read-only today). | `engine/extraction/gate.py:385` | opportunistic (A1 §A2 rerun) |
| M-15 | The gate report records no digest of the answer key or the corpus builder. | `engine/extraction/gate.py:331-354` | A1 (§A2 rerun) |
| M-16 | A VLM leg that fails to RUN is appended to `vlm_findings` and reads as fabrication. | `engine/extraction/gate.py:481,175` | A1 (§A2 rerun) |
| M-17 | `_tree_files` hides dot-prefixed paths from both the manifest and the extras check. | `engine/extraction/weights.py:51-55,121-128` | A1 (§A2 rerun) |
| M-18 | `media.py` promises `FigureView` objects or dicts; the inner loop is dict-only. | `engine/extraction/media.py:26-29` | opportunistic |
| M-19 | `files_fingerprint` concatenates bytes with no separator or path (ambiguous by construction; fixed lists today). | `engine/evals/cases.py:35-41` | opportunistic (P26b) |
| M-20 | `load_trace` joins a case-supplied name into two directories with no containment check and falls through to the live-run directory (cases are committed). | `engine/evals/trajectory.py:30-39` | opportunistic (P26b) |
| M-21 | `max_cost_usd` treats a call missing `cost_usd` as free (the no-calls case is guarded). | `engine/evals/trajectory.py:90-92` | opportunistic (P26b) |
| M-22 | `resolver.py:23` says "30 registry entries"; there are 35 (36 after P0-15). | `engine/metrics/resolver.py:23` | P26a Group E (with P0-15) |
| M-23 | `extraction.json` is json-loaded with no guard in a resolver — one corrupt artifact takes down the view render (P0-14's class). | `engine/metrics/resolver.py:411` | P26a Group C (with P0-14) |
| M-24 | `Corpus.runs()` re-flattens per call; `_r_fact_sheet_staleness` calls it twice in three lines (correctness-neutral). | `engine/metrics/resolver.py:72-74,334` | opportunistic |
| M-25 | `_last_run_status` sorts run files lexicographically while `latest_run_id_in` sorts numerically (correct while ids stay 4-digit; the helper exists and is unused). | `engine/web/state.py:44-54` · `workspace/pursuit.py:45-49` | P26a Group C (with P2-20) |
| M-26 | The anonymization eval has no non-vacuity guard: a case with neither `labels` nor `must_not_contain` skips silently (`expected` is not required by the schema); all 22 cases carry labels today. | `engine/kb/evalset.py:143-148` · `schemas/eval-case.schema.json:7` | P26b |
| M-27 | The same harness inspects `cards/*.md` only while ingestion scans the L1 model too — an identifier surviving into `kb/canonical/` but not a card is invisible to the suite. | `engine/kb/evalset.py:131-134` · `ingest.py:555-566` | P26b |
| M-28 | `descend` reads its anchor card with no `use_restriction` check and emits its heading path — a restricted card's document position is enumerable through the assistant; neighbours are correctly excluded. | `engine/kb/retrieve.py:210-220,245-256` · `assistant/tools.py:125-138` | P26b (with P1-13) |
| M-29 | `card_search` applies the per-query `exclude` set BEFORE idf, which `rank.py`'s corpus-statistics law forbids; no caller passes `exclude` today. | `engine/kb/retrieve.py:161-172` · `rank.py:5-6` | opportunistic (P26b) |
| M-30 | `ProposalStore.list` json-loads every `prop_*.json` with no defence — one hand-authored bad file 500s the steward inbox (torn writes closed by P0-6). | `engine/flywheel/proposals.py:73-78` | P26b (with P1-39) |
| M-31 | `pings.py` still hand-rolls append+fsync beside the new `append_fsync`; and no atomic writer fsyncs the containing DIRECTORY after `os.replace` (the rename itself is not crash-durable — documented limit). | `engine/web/pings.py:41-46` · `engine/contracts/atomic.py` | P26a Group B (the append; the directory fsync is a documented limit) |

**Confirmations worth the record (checked sound):** spend discipline in evals (every live path behind `--live` + `LiveCaller`'s three refusals; one `SpendBudget`; a crashed live run still closes its log); baseline archive-before-overwrite; `code_fingerprint` a real fourth lock; the intake and voice lanes' denominators drift-pinned; the registry/resolver bijection; the docker command injection-free (`argv`, `:ro`, `--network none`); weights verification bidirectional; ping and gap id minting under `_mutate` (not a P1-20 sibling); the attribution join exactly as claimed; `emit_kb_retrieval` a real choke point; the card render/parse round trip; `snapshot_id` honest; reconciliation's matcher deterministic and unable to classify a drift as `matched`; store path handling not a traversal risk beyond P2-23; the access log writes before it authorizes; the evalset exclusion control structural; `pursuit_memory` unable to reach the fact sheet; three-state discipline in `state.py` and the flywheel metrics.

### 5.8 P26a closure (2026-09-02, B109)

Closed by P26a, each with a named test in the suite: **P1-27** (item 1 — the
hand-completion door + the two-copy fill; `tests/assembly/test_template_fill.py`,
`test_hand_fill.py`, `tests/web/test_template_fill_web.py`, `test_hand_fill_web.py`)
· **P0-1, P1-16, P1-28, P2-15, P2-14, P3-13** (Group A; `tests/llm/test_live_caller.py`,
`test_sdk_shape.py`, `test_handoff_caller.py`, `tests/contracts/test_llm_boundary.py`,
`tests/web/test_payload_types.py`) · **P0-6, M-11, P1-14, P2-29b, P2-31, M-31**
(Group B; `tests/contracts/test_atomic_writes.py`, `tests/revision/test_round_crash.py`,
`tests/drafting/test_control_chars_draft.py`, `tests/revision/test_round_control_chars.py`,
`tests/web/test_comment_control_chars.py`, `test_export_control_chars.py`,
`tests/contracts/test_draft_prose_pattern.py`) · **P1-17, P2-20, P0-14, P1-35, P1-36,
P2-44, P2-49, M-23, M-25** (Group C; `tests/runlog/test_torn_tail.py`,
`tests/web/test_jobs_close_runs.py`, `test_runs_read_model.py`, `test_board_truth.py`,
`tests/cli/test_recovery_runbook.py`) · **P0-10, P1-15, P0-11, P0-13, P0-21, P2-47,
P2-48** (Group D; `tests/contracts/test_advisor_docs.py`, `tests/web/test_server_clock.py`,
`test_share_waiver_privacy.py`, `tests/strategy/test_gate_notes_survive.py`,
`tests/contracts/test_runlog_gate_notes_schema.py`) · **P0-9, P2-32, P2-33, P2-34, P0-15,
P1-32, P1-33, P1-34, P2-42, P2-43, M-22, P0-12** (Group E;
`tests/evals/test_release_regression.py`, `test_trajectory_pattern.py`,
`tests/metrics/test_sweep_riders.py`, `tests/contracts/test_gate_dockerfile.py`,
`test_lock_hashes.py`). Suite at close: 1687. Ids remain permanent labels;
nothing here renumbers.

**Finding at the close (B109 §4), home A1 §A2 rerun:** an unconstrained rebuild
of the gate image resolved docling 2.124 / ibm-models 4.0, under which the
ruled-table PDF extracts with zero grids and three more container tests fail —
the container install is now constrained by `requirements-extraction.lock`, and
the next deliberate docling bump re-runs the gate before the lock moves.

### 5.9 P27 wave-1 kickoff — one finding at planning (2026-09-02, B110)

*Read at P27 planning against `7682383`, before any wave-1 code: the effort
schema against the three gate doors that will carry effort once the
workbench produces it. Re-read at the cited lines before entry; the id
continues the numbering and has exactly one home (the B94 door).*

| id | finding | where | home |
|---|---|---|---|
| P1-42 | **A gate-0 decision carrying effort fails AFTER the decision lands.** The effort block's `gate` enum is `gate_1 \| gate_2 \| review_loop \| final_signoff` — no `gate_0` — while the gate-0 door defaults `effort.gate = "gate_0"` and appends the review_session only after the decision commits, so the append is refused over an already-decided gate: the P25-item-1 failure mode through a door P25 never exercised. Latent today only because nothing in the UI produces effort. | `schemas/feedback-event.schema.json` (effort `gate` enum) · `engine/web/server.py:1489,1506` | **P27 wave 1** (step 2: a failing test first, then the enum in its own schema commit) |

**P26b pre-read (no new ids; recorded for that slice's step 0).** The
thirty-three P26b ids re-located at `7682383`: seven implementation groups
(the parser-fidelity carrier P1-23 first, then the KB store integrity set,
ingest/reconcile idempotence, the flywheel wiring at accept, eval integrity,
the output/web boundary; every M-id folds into one of them). Two citations
sharpen: `docx_buyer.py:379-386` (`question_cell_map`) raises on a ragged
table at write-back too, so P2-30's scope includes the write-back
re-derivation; `server.py:1424`'s gate-time forecast parses a target with no
run log in scope, so P1-23's drain must name that path. The run-log schema
has no `warning` record type — P1-23's channel either reuses
`error{recoverable: true}` (the planner's existing idiom) or adds a record
type in its own schema commit; decided at P26b step 0, not here.

**Closed by P27 wave 1 (2026-09-02, B111), each with a named test:** **M-9**
(the role half — `tests/web/test_session_role.py`, `test_workbench_source.py`,
`tests/metrics/test_effort_attribution.py`, `test_waiver_session_role.py`) ·
**P1-42** (`tests/web/test_gate0_effort.py`) · **P2-5's wave-1 half** (the
curl doors, share management, the waiver screen, the ping inbox, the guest
page, the review-loop doors — `tests/contracts/test_ui_surfaces_doors.py`
pins every wave-1 door as `ui`/`guest`; `tests/web/test_share_page.py`,
`test_review_last_round.py`; wave 2's half — revision-diff view, ARIA/dialog
semantics, focus management, poll error handling — stays open in the P27
row) · **P1-7's UI half** (the ping inbox has a screen; the delivery channel
is still the owner's choice — the id stays open on that half). Suite at
close: 1728. Ids remain permanent labels; nothing here renumbers.

### 5.10 P26b split three ways; P26b-1 kickoff — no new ids, four citations sharpened (2026-09-03, B112)

*Read at P26b-1 planning against `be2a393`. The thirty-three P26b ids
now have three homes — P26b-1 parser fidelity (P1-23, P1-24, P1-25,
P1-26, P2-26, P2-27, P2-30, P1-29, P2-23, P3-14), P26b-2 KB integrity +
flywheel (P1-13, P1-21, P1-37, P1-38, P1-39, P1-40, P1-41, P2-45, P2-50,
P2-46, M-27, M-28, M-29, M-30), P26b-3 eval integrity + output boundary
(P2-35, P2-36, P2-37, M-19, M-20, M-21, M-26, P1-19, P3-15) — the
owner's call on the sizing recorded in B112 §1. P1-37, P1-38 and M-27
move from the parser group to P26b-2: they are ingest/reconcile items
sharing files with P2-46. The eval-integrity trio lands last because two
eval lanes score the parser directly (`engine/evals/structure.py`,
`engine/evals/intake.py`) and P26b-1 moves those numbers. Ids remain
permanent labels; nothing here renumbers.*

**Citations sharpened at `be2a393` (the rows above are not edited; this
note supersedes their `where` cells):** P2-30's write-back re-derivation
`question_cell_map` is called from `engine/assembly/docx_writeback.py`
(`compute_docx_facts`), not `writeback.py`; the write-back PREVIEW door
catches only `ContractError`/`FileNotFoundError`, so even a typed refusal
500s there today — P26b-1 widens it. P1-23's forecast path is
`_preflight` in `engine/web/server.py` (~:1454), a gate-time cost forecast
with no run log that swallows every parse failure by design; it stays
unwarned — the plan-time parse is the recorded one. P1-25's precedent is
`engine/kb/xlsx.py` ~:139-143. P1-29 has two escapes the row does not
list — `KeyError` on a worker result missing `view`, and the same
unguarded `from_dict` in `InContainerBackend.convert` — and a third gap
(a non-zero exit WITH stdout falls through to the parse). P1-26's
docstring half landed at P25 item 6 as hedged wording; the code gap is
the remaining half. P1-23's class has a fourth silent drop the row does
not cite — `engine/structure/conventions.py` `answer_cells` drops a whole
row when a formula sits in a labeled column (the grid TOTAL row); it is
inside P1-23's stated class ("every row that falls through … dropped
with zero record") and closes with it, no new id.

**P1-24's scope (the owner's call):** a formula question cell becomes a
slot from the cached value a second `data_only=True` load supplies;
`PARSER_VERSION` 2.0.0 → 2.1.0 with the pre-P16 byte pin re-pinned in the
same commit, per that test's own procedure; no cached value → a warning,
no slot. The structure eval's golden set (the P16 four) is unchanged — no
committed twin carries a cached value; the new formula twin is a unit
fixture.

### 5.11 P26b-1 closure (2026-09-03, B113)

**Closed by P26b-1, each with a named test:** **P1-23** (`tests/structure/test_parse_warnings.py`, `test_docx_parse_warnings.py`, `tests/planning/test_plan_warnings_drain.py`) · **P1-24** (`tests/structure/test_formula_questions.py`; PARSER_VERSION 2.1.0, the pre-P16 pin re-captured in the same commit) · **P1-25** (`tests/intake/test_extract_formulas.py`) · **P1-26** (`tests/intake/test_hidden_columns.py`) · **P2-26** (`tests/intake/test_pdf_recovery.py`) · **P1-29** (`tests/extraction/test_worker_result.py`) · **P2-27** (`tests/structure/test_docx_parts.py`, `test_docx_buyer_parts.py`, `tests/intake/test_extract_docx_parts.py`, `tests/kb/test_read_docx_parts.py`) · **P2-30** (`tests/structure/test_docx_buyer_ragged.py`, `tests/web/test_writeback_ragged.py`) · **P2-23** (`tests/kb/test_id_shape.py`, `tests/web/test_kb_id_doors.py`) · **P3-14** (`tests/web/test_comment_slot_id.py`). Suite at close: 1810. Ids remain permanent labels; nothing here renumbers.

**Stated limits (B113):** the gate-time forecast (`_preflight`) still parses without a log and stays unwarned by design; the firm template parser's drops (`docx_default.py`) are outside P1-23's buyer-document class; the id shape is "prefixed and path-safe", of which the minted hex form is a subset; P1-25 keeps formula source text in the intake output (EC-5's never-thinned contract) — marked, with the cached value beside it or a warning in its place; headers/footers are read by intake and KB and recorded as present by the buyer parser, which bears no slots from them.

### 5.12 P26b-2 closure (2026-09-04, B115)

**Closed by P26b-2, each with a named test:** **P1-37** (`tests/kb/test_reingest.py::test_third_ingest_after_drift_is_idempotent`) · **P1-38** (`test_reports_against_different_priors_coexist`) · **M-27** (`tests/kb/test_anonymization.py::test_harness_catches_a_leak_in_the_canonical_model_only`) · **P2-46** (`tests/kb/test_provenance_access.py::test_source_doors_log_and_authorize`, `test_prior_models_goes_through_the_door`; schema commit pinned by `tests/contracts/test_access_log_schema.py`) — the doors log and authorize; the walk's orphan blindness (a `.src` with no meta, invisible to `source_metas`, surviving every purge as CLEAN) was P2-59, closed by P29b b6 (B133: `orphan_source_ids` composes the two logged walks; every purge removes and names an orphan; `write_source` writes the meta first) · **P1-13** (`tests/kb/test_org_purge.py` and `tests/kb/test_pursuit_purge.py`: the empty-lane gate and the accounting guard, two tests each) · **P1-40** (`tests/kb/test_curation_concurrency.py`, `tests/contracts/test_locks.py`, `tests/web/test_curation.py::test_concurrent_merge_through_the_route`; `kb_merge` maps `ProposalStateError` to 409 like the reject leg since P3-22, P29b b7) · **P1-21** (`tests/kb/test_merge_batch_atomic.py`; the batch's input contract — a repeated id applied twice and logged as `aborted` — was P3-22, closed by P29b b7) · **P1-39** (`tests/flywheel/test_proposal_state.py`, `tests/web/test_curation.py::test_accept_then_reject_is_refused`) · **M-30** (`tests/web/test_kb_inbox_bad_file.py`, `test_proposal_state.py::test_a_file_that_is_not_a_proposal_refuses_by_name`) · **M-28** (`tests/kb/test_descend.py::test_restricted_anchor_descends_to_recorded_empty`) · **M-29** (`tests/kb/test_retrieval.py::test_exclude_does_not_move_scores`) · **P2-45** (`tests/flywheel/test_survival.py::test_long_section_scores_are_length_independent`) · **P2-50** (`tests/flywheel/test_routing.py::test_a_changed_number_reads_as_factual_whatever_its_digits`) · **P1-41** (`tests/web/test_flywheel_accept.py`, `tests/web/test_events.py::test_append_revised_keeps_the_id_and_refuses_an_unknown_one`, `tests/flywheel/test_survival.py::test_a_routed_copy_does_not_double_count_its_edit`). Fourteen ids; the P26b row's middle third is closed. The register's line anchors for `ProposalStore.list`/`.decide`, the KB routes, `descend` and `merge_batch` had moved since the review (B114 §4); the findings themselves stood.

**Stated limits (B115):** cross-process exclusion stays the workspace flock; `superseded` has no producer; ingest's card writes are outside the KB lock (its one firm-KB write is inside); a zero-edit accept writes `edit_survival` 1.0 to every cited production card by the documented semantics; flywheel proposals are decide-only in the inbox; the lag span's second half awaits a multi-generation corpus.

**Remaining in P26b-3 (unchanged):** P2-35, P2-36, P2-37, M-19, M-20, M-21, M-26, P1-19, P3-15 — written against the 0.6.0 record.

### 5.13 P26c kickoff — two findings at planning (2026-09-04, B116)

*Planning P26c (flywheel carry-forward, the owner's call at B115 §10) found the accept-and-nothing-happens class wider than §5.12's stated limit. Two ids, each with one home; item 3 of the slice (inbox rendering) is workbench scope and takes no id (the §5.9/B113 precedent).*

| id | finding | where | home |
|---|---|---|---|
| P1-43 | **Accepted proposals with no home.** Five shapes decide and change nothing: the flywheel's `update_card` (no `kb_id`, `diff.text`); `voice_spec_change` / `playbook_note` / `validation_tuning_note` (no home exists — `playbook` is a schema enum with zero cards and zero code, `validation_tuning` is four enum strings); `deprecate_card` (`diff.status` is not a card field, and pass 1 never checks the card still exists); `outcome_backlabel` (no producer, P3-4); and the web decide door never passes `fills`, so a fact-sheet `new_card` always 409s from the UI. A steward who accepts and sees nothing happen reads the product as broken. | `engine/kb/curation.py::_merge_batch_locked`, `engine/web/server.py` decide/merge doors, `engine/web/static/app.js` inbox | **P26c item 1** (homes: a lessons record on the cited card, notes as the accepted proposals, a `deprecated` block honoured by retrieval, a typed refusal for the backlabel) + **item 3** (the fills form) |
| P1-44 | **Human feedback beyond edits never reaches the flywheel.** `route_edits` consumes `edit` events only: comment events with their agent replies (and the round's finalize drops a comment's `edit_reason`), `waive_block` events (the reason and claim text sit on the annotated-draft claim), answered gaps (opt-in card proposals only, B69 §7) and the hand-fill record are invisible to the learner, so what the human said or built is lost to the corpus. Carried text is pursuit prose and must be placeholdered before it lands on a firm card. | `engine/flywheel/routing.py`, `engine/web/learn.py`, `engine/revision/round.py::_finalize`, `engine/validation/waiver.py`, `engine/assembly/hand_fill.py` | **P26c item 2** (comments, waivers, gaps at accept; hand-fills at writeback confirm; placeholdering at open) |
| P0-22 | **The workbench script does not parse.** `loadDownloads` in `engine/web/static/app.js` declares `const dl` twice in one function — a parse-time SyntaxError, so a browser loads NONE of app.js: every screen the P27 wave-1 row claims "needs no terminal" has been dead from `pilot-2.3` through `pilot-2.5`. No test parses the static scripts (the surface pins read path literals). Found in P26c while touching the inbox rendering. | `engine/web/static/app.js::loadDownloads` | **P26c (fixed the same commit; guard `tests/contracts/test_static_js_parses.py` parses every static script with node or JavaScriptCore and skips by name where neither exists)** — the UAT click-through (B111 §5) stays the human half |
| M-32 | **The release-mode cut litters the system temp root.** `release_commit` clones the public mirror into `tempfile.mkdtemp(prefix="rfp-public-release-")` with no `dir`, and the orchestration tests run release mode on every gate — 150 abandoned clones accumulated in three days. Found at the P26c close while cleaning this session's staging. | `tools/public_cut.py::release_commit` | **P26c close (fixed the same commit: the clone lands beside the staging dir, so under pytest it is cleaned with tmp_path; `tests/contracts/test_public_cut_orchestration.py::test_release_mode_runs_the_deletion_guard` pins it)** |

**Closed by P26c (2026-09-04, B117), each with a named test:** **P1-43** (withheld from `open_card`, search and descent at P26c; the assistant's `card_detail` door handed the model the body until P2-60 — P29b b7, B133, the same predicate and trace line at both doors; `tests/kb/test_merge_batch_atomic.py::test_a_flywheel_text_diff_lands_as_a_lesson` and its four siblings, `tests/kb/test_proposal_homes.py`, `tests/kb/test_store.py::test_a_card_takes_lessons_and_deprecated`, `tests/kb/test_retrieval.py::test_deprecated_withheld_and_recorded`, `tests/kb/test_descend.py::test_deprecated_anchor_and_neighbor_are_withheld`, `tests/kb/test_notes.py`, `tests/drafting/test_draft_frames.py::test_an_accepted_playbook_note_reaches_the_drafter`, `tests/revision/test_rounds.py::test_an_accepted_note_reaches_the_reviser`, `tests/web/test_curation.py::test_the_inbox_names_every_proposals_home`, `::test_a_fact_card_accepts_from_the_ui_with_fills`, `tests/web/test_flywheel_accept.py::test_accepting_the_lesson_lands_it_on_the_card`) · **P1-44** (`tests/flywheel/test_routing.py` — seven tests from `test_an_edit_proposes_onto_every_cited_card` to `test_carried_text_is_placeholdered_at_open`; `tests/revision/test_rounds.py::test_a_comments_reason_rides_its_finalized_event`; `tests/web/test_flywheel_accept.py::test_a_comment_and_a_waiver_reach_the_inbox_with_their_events`, `::test_an_answered_gap_reaches_the_inbox_once`, `::test_the_buyer_name_is_placeholdered_in_the_proposal`; `tests/web/test_template_fill_web.py::test_confirm_proposes_the_case_block_not_the_grid`; `tests/kb/test_pursuit_purge.py::test_a_pursuit_purge_strips_its_proposals_and_lessons`) · **P0-22** (`tests/contracts/test_static_js_parses.py`) · **M-32** (`tests/contracts/test_public_cut_orchestration.py::test_release_mode_runs_the_deletion_guard`, the litter assertion) · and B117 §6's first limit closed post-close: `targeted_open` refuses a deprecated card (`tests/kb/test_retrieval.py::test_targeted_open_refuses_a_deprecated_card`). Also shipped on the owner's word (B115 §9c): the real-clock gate test's walk waits the suite-wide 180s, and `tools/public_cut.py` names a red test (`tests/contracts/test_public_cut_orchestration.py::test_a_red_suite_in_the_cut_tree_names_what_failed`).

**Stated limits (B117 §6, one closed the same day):** validation-tuning notes are human-read until A4; the waiver join is (actor, at, section); hand-fills route only the case block; `purge_client` never guesses a client's pursuits — its carried-forward text is stripped by purging the pursuits, and the widened sweep names any survivor; the drafter frame carries the last 20 accepted notes per target.

**Remaining before A1: P26b-3** (P2-35, P2-36, P2-37, M-19, M-20, M-21, M-26, P1-19, P3-15) at 0.8.0, against the 0.7.0 record.

### 5.14 The CI touch — one finding from the owner's inbox, P2-28 taken (2026-09-04, B118)

*GitHub's usage notice (90% of the plan's included Actions minutes, five days after the workflow first ran) arrived in the owner's inbox; the count below is from the Actions API, not the notice. P2-28 was parked on "the next CI touch" — this is that touch.*

| id | finding | where | home |
|---|---|---|---|
| M-33 | **The private repo's macOS CI leg consumed the month's included Actions minutes.** The matrix runs ubuntu + macOS on every push to `main`; macOS bills at 10x. Since the workflow's first run (2026-08-31): 26 runs, 187 ubuntu + 184 macOS raw minutes = ~2,028 weighted, against 2,000 included — the public mirror's identical runs cost nothing. With the default zero spending limit the consequence is not a bill: private-repo runs stop queuing until the cycle resets, and every push after that lands unproven. | `.github/workflows/check.yml` `strategy.matrix` | **Paused, not ended (B118 §2, this commit):** the matrix is an expression — macOS only where `github.event.repository.private` is false, so the same file proves both platforms at every release cut in the mirror and ubuntu alone on private pushes (~78 → ~7 weighted minutes a push). **Reopen trigger:** the private repo's minutes stop being the constraint (a paid Actions plan or a self-hosted macOS runner), or a macOS-only bootstrap regression ever reaches a cut. |

**P2-28 closed here (B118 §3), except its Node pin half:** the token step runs on `push` only (a same-repo `pull_request` never gets the list on disk — on the private repo it reds at the tripwire, loudly), `enable-cache` is `push`-only (a branch can no longer seed what `main` restores) and keyed on `requirements.lock` (the default glob matched nothing, so the cache could never invalidate — a live run warning), `persist-credentials: false` on the checkout. `actions/checkout` bumped v4.4.0 → v5.1.0 (Node 24 — the runner's deprecation annotation named it; the only v5 change beyond Node is a `pull_request_target` default this workflow does not use). **Still parked, with its trigger:** `astral-sh/setup-uv` v5.4.2 → v7+ — the first Node 24 release stacks v6's breaking input changes; reopens when GitHub names the Node 20 removal date or the action reds. No test can prove a workflow file locally; the proof is the next private push (one job) and the next release cut (two).

### 5.15 P26b-3 kickoff — no new ids, three premises corrected (2026-09-04, B119)

*Read at P26b-3 planning against `0404d74`. The nine ids (P2-35, P2-36, P2-37, M-19, M-20, M-21, M-26, P1-19, P3-15) keep their homes; the owner's three calls are B119 §1. Ids remain permanent labels; nothing here renumbers.*

**Premises corrected (the rows above are not edited; this note supersedes their `finding`/`where` cells where they differ):** **P1-19** — the reproducible loss on openpyxl 3.1.5 is the CACHED FORMULA VALUE (`<v>` emptied on every load/save; `data_only=True` reads `None` afterwards), which P26b-1's parser now relies on; charts, cell comments and data validation survive the round trip; images drop only because Pillow is absent from the lock. The row's remedy ("assert … refuse on drift") would refuse most Excel-authored forms, so the home is a zip-level cell patch that copies every other part verbatim (B119 §1a) — the round-trip assert then proves exactness rather than gating a refusal. **P3-15** — five `.save(` sites in four assembly modules (not seven in five): `writeback.py`, `docx_writeback.py`, `docx.py` ×2, `template_fill.py::_render` ×2 calls; `engine/kb/xlsx.py` and `engine/evals/structure.py` write non-buyer files and are outside the class. There is no firm-name setting or reader anywhere in the repo — the identity is minted as a workspace `firm.json` (B119 §1c). **P2-37** — the finding's own demonstration is `tests/evals/test_remeasure_harness.py::test_live_recording_writes_the_result_file`, which records a "live" result under a lambda with zero credentials. **M-19** — the only multi-file caller is the poison lane's `prompts_fingerprint` (two prompt files); the ambiguity is latent (fixed rosters) and the fix moves all three committed digests, re-pinned without re-measure under a same-commit proof (B119 §4). **P2-36** — every committed denominator is non-zero, as B112 §2 said, so the floors change no number; the smallest are intake's date cases (2) and consistency's code-detectable set (5).

**Closed by P26b-3 (2026-09-04, B120), each with a named test:** **P2-36** (`tests/evals/test_vacuous_rates.py`) · **M-26** (`tests/kb/test_anonymization.py::test_a_case_that_asserts_nothing_fails_the_eval`) · **M-19** (`tests/evals/test_shared_cases.py`, `tests/evals/test_baseline_lock.py::test_the_re_pin_hashed_the_same_bytes`) · **P2-35** (`tests/evals/test_baseline_lock.py`) · **P2-37** (`tests/evals/test_remeasure_harness.py`) · **M-20** (`tests/contracts/test_paths.py`, `tests/evals/test_trajectory.py::test_a_trace_name_cannot_escape_either_directory`) · **M-21** (`tests/evals/test_trajectory.py::test_a_call_without_cost_is_unmeasurable`) · **P3-15** (`tests/contracts/test_bundle_hygiene_schema.py`, `tests/assembly/test_output_hygiene.py`) · **P1-19** (`tests/assembly/test_xlsx_patch_roundtrip.py` over `tests/fixtures/writeback-twin.xlsx`). Nine ids; the P26b row is closed in full (10 + 14 + 9). Suite at close: 1943. Ids remain permanent labels; nothing here renumbers.

**Stated limits (B120 §6):** the lock catches a single-file edit, not a two-file forgery; `docProps/app.xml` untouched; `fullCalcOnLoad` not set; Excel's tolerance of inline-string answers is the UAT's to open; the older inline containment copies migrate on next touch.

### 5.16 P28 kickoff — two findings at planning, P1-4 re-scoped (2026-09-05, B121)

*Planning P28 (anonymization depth, the last B91 §3 A1 precondition that is engineering rather than the owner's) against `dae1a16` found the A1 line "real corpus ingestion under the anonymization gate" gated by two untracked holes beside P1-4. Two ids, each with one home; the owner's three calls are B121 §1. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-45 | **The production ingest door has no live caller.** `rfp kb ingest` requires `--wire`, a scripted model reply standing in for the model ("the live caller lands P8" — it never did). `ingest_document`'s only callers are that CLI, the eval harness and a test fixture; the web has no ingestion door. At A1 every real document would need a hand-written wire, so the anonymization gate would never see a live model's proposal in production. | `engine/cli/kb.py::_cmd_kb_ingest`, `register` | **P28 step 4** — `rfp kb ingest --live` over the traced live caller (RFP_LIVE-gated by construction) with a shared spend budget; offline the operator supplies both wires |
| P1-46 | **Flywheel proposals are substituted, never scanned.** `learn_from_accept` / `learn_from_writeback` hand `apply_placeholders` to `route_feedback`; `scan` is never called on that path, and the identifier index there is the brief's buyer name plus org aliases — nothing else. A reviewer comment naming a subcontractor, or carrying an email, lands in `kb/proposals/` (steward-visible, drafter-read once accepted) with no gate. | `engine/web/learn.py`, `engine/flywheel/routing.py::route_feedback` | **P28 step 5** — `route_feedback(verify=…)` runs the ingestion scanner over every proposal string; a hit is not written and the learn report names the event and locations |

**P1-4, re-scoped (B121 §1):** the row's remedy ("NER/second-model cross-check and an adversarial eval set") ships in P28 as engineering — the taxonomy from the domain (six classes, the owner's call), code-side structured detection, a second-model cross-check AT INGESTION, twenty adversarial cases each proven to bite, and a live arm that refuses to call itself live and records its measure. What P28 cannot close is the live measurement itself: the recorded live result (`evals/anonymization/live-record.json`) is A1's acceptance line, and until A1 runs it the release record says `not_measured` with the reason. **Citations corrected (no ids):** the two contact regexes are the only model-independent detection today and they block rather than substitute; the eval's `caller_factory` is ungated; the lane's `detail` hand-cites B35; the spec taxonomy is three types and an ellipsis; the pre-export scan (S3) stays homed at A6.

**Remaining before A1 after P28:** the owner's acts (P1-2, P1-9 attestations; data governance; the A1 live anonymization run) and P1-6, which needs the real corpus. Total tracked: 165.

**Closed by P28 (2026-09-05, B122), each with a named test:** **P1-45** (`tests/cli/test_kb_ingest_live.py` — refusal legs proven at P28; the capability leg P2-53, closed by P29a) · **P1-46** (`tests/flywheel/test_proposal_leak_scan.py` — the accept-time route proven at P28; the opt-in doors P1-49 and the write-back door's record P3-23, closed by P29a) · **P1-4 — engineering shipped** (`tests/kb/test_anonymization_taxonomy.py`, `tests/kb/test_anonymization_cross_check.py`, `tests/kb/test_anonymization.py` at 42 cases, `tests/evals/test_anonymization_live_arm.py`); the row stays open on ONE line, A1's: the recorded live measure (`evals/anonymization/live-record.json`, `docs/uat/a1-anonymization-live.md`) fresh against the current corpus fingerprint with `pass: true` — until then the release record says `live: not_measured` by name (the record is trustworthy since P29a closed P1-50, P2-54 and P3-18: a fresh store per case per run, a fingerprint naming every input, an atomic write). Suite at close: 1978. Ids remain permanent labels; nothing here renumbers.

**Stated limits (B122 §6):** an unstructured third-party name neither reader lists is invisible to the code gate (pinned as the limit); the structured detectors are regexes with a closed TLD list and English street types; a one-decimal fee rounding can collide with a neighbouring figure (a block a human clears); the offline doubles read the answer key — A1 measures the readers.

### 5.17 Post-P28 delta audit, chunk 1 — anonymization-ingest + closure-claims (2026-09-05, B124, against `270e275`)

*The first chunk of the adversarial audit of everything shipped since this review (`626522a..HEAD`, B123 §4): two finders (the anonymization/ingest surface; every closure claim in §5.6–§5.16 against its named test), each raw finding then verified by independent refuters and a reproducer that had to make it fail in the repo. Eight raw, seven distinct, seven survived — each reproduced with real output at HEAD, none already on the register. Five sit on the ingestion gate P28 just closed; two are closure-strength gaps (the fix shipped, the named test does not drive it). The closure-claims finder checked and CLEARED every other id closed in P25–P28 (the list is in B124 §3). Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-47 | **The ingest proposal note persists the source FILENAME — in practice the client's name — unscanned in `kb/proposals/`.** `_cmd_kb_ingest` sets `doc_id=Path(args.file).stem` (`engine/cli/kb.py:112`); the claim-promotion proposal's `note` embeds `doc.doc_id` (`engine/kb/ingest.py:843`); the gate's scan texts (`ingest.py:665-675`) cover element text, claim text and card title/summary/body — never the note. A source file named after the client therefore writes the client's full name into a steward-visible proposal record, in a tree `.gitignore` does not cover (it lists `kb/runs/`, `kb/restricted/access.jsonl`, `kb/reconciliation/` — not `kb/proposals/`), while every card is correctly placeholdered and the report reads `ingested` with zero findings. The same stem reaches the run log on the buyer-authored refusal line (`ingest.py:457`). The gate comment at `:657-660` claims the proposal text is scanned. Fix shape: the note and the run-log line carry a neutral document handle (the content hash or a minted id), never the stem; the note joins the scan texts as the belt. *Proven:* the real argparse path with a client-named file returns rc 0, cards grep clean, and the proposal file's note carries the client name verbatim; `git check-ignore` on the path returns 1. | `engine/kb/ingest.py:843,457,665-675` · `engine/cli/kb.py:112` · `.gitignore` | **pre-A1 rider (proposed P29)** — blocks A1's "real corpus ingestion under the anonymization gate" |
| P1-48 | **`question_forms` are substituted but never scanned — acronyms and partial names land in card frontmatter.** `card["question_forms"] = [_anon(q) for q in forms]` (`ingest.py:392`) runs substitution only; the scan texts never include the forms, so the widened scan (acronyms, distinctive tokens, fee restatements) never sees the questioner's output. The comment at `:389-391` says "anonymized like every other model output"; for every other model output the belt is substitution AND scan. Latent today (production passes `questioner=None`), live the day the questioner seam is wired. Fix shape: add `{kb_id}:form:{n}` entries to the scan texts. *Proven:* with both readers indexing the client and a questioner returning one acronym form and one partial-name form, status `ingested`, findings `[]`, and the written card's `question_forms` carry both variants; a control `scan` over the same strings returns two findings. | `engine/kb/ingest.py:386-392,665-675` | **pre-A1 rider (proposed P29)** — reopen trigger if deferred: wiring the questioner seam |
| P2-51 | **A fee identifier indexed WITH cents generates no restated-form variants.** `_fee_variants` returns early on `if "." in digits` (`engine/kb/anonymize.py:186-187`), before the K-form and M/MM/million blocks; the exact regex for a cents form requires the literal `.00`. The readers copy fee tables verbatim, so the cents spelling is the likely indexed one; the cover letter's un-cented figure and the summary's `M` restatement then pass substitution and the scan. B122 §6 names the one-decimal rounding collision as a limit, not this. Fix shape: when the decimal part is zero cents, derive the integer family as well. *Proven:* the cents form yields only its two separator variants; `scan` over the un-cented restatement, the `M` form and the "dollars" form returns `[]` for all three; indexing the un-cented form catches all three. | `engine/kb/anonymize.py:186-202` | **pre-A1 rider (proposed P29)** — same commit as P2-52; the 42-case eval gains the case |
| P2-52 | **NFC does not fold typographic ligatures, so a ligature-spelled client name escapes the metadata-known identifier.** `normalize_text` applies NFC (`anonymize.py:94`), which leaves the `ﬁ`/`ﬂ` compatibility characters (U+FB01/U+FB02 — common in text pasted from a PDF render) intact; `_identifier_regex` and `_distinctive_tokens` key on the same normalization, so the `--client` name matches neither the exact form nor its token when the document spells it with the ligature. The module docstring claims Unicode spellings neither escape substitution nor hide from the scan. Fix shape: NFKC (or NFC plus an explicit ligature fold) in `normalize_text`; the eval gains a ligature case. *Proven:* end-to-end `ingest_document` with the known client and a ligature-spelled mention: status `ingested`, findings `[]`, the retrievable card text carries the ligature spelling of the client; the ASCII control substitutes to `[CLIENT]`. | `engine/kb/anonymize.py:94,111-112,152` | **pre-A1 rider (proposed P29)** — same commit as P2-51 |
| P2-53 | **P1-45 is closed on its refusal legs only; the live CAPABILITY leg has no test.** §5.16 names `tests/cli/test_kb_ingest_live.py`; its five tests are refusal without `RFP_LIVE`, `--live`/`--wire` exclusion, `--reviewer-wire` refused under `--live`, offline two-wire refusal, offline two-wire success. Nothing drives `--live` with the flag present, so `_live_ingest_caller` (`engine/cli/kb.py:47-64`) and the branch at `:95-110` are never executed by the suite. Signatures match at HEAD — untested, not broken — but a renamed kwarg, a changed `model_prices()` shape, or `max_calls=8` falling below one document's reads would break the production door at A1's first real document with `make check` green. CLAUDE.md's law: a refusal-only tested state reads as unfinished; §5.16 read it as closed. Fix shape: the positive twin the eval lane already has (`tests/evals/test_remeasure_harness.py:108-131`, `live_env` + a stub client at zero spend) asserting both agents reach `ingest_document` through the traced caller under the budget. *Proven:* a scratch positive leg passes at HEAD and goes red under a sabotaged `_live_ingest_caller`, while all five shipped tests stay green under the same sabotage. | `engine/cli/kb.py:47-64,95-110` · `tests/cli/test_kb_ingest_live.py` · §5.16 | **pre-A1 rider (proposed P29)** — test-only; §5.16's P1-45 line amended when it lands |
| P3-16 | **P1-18's fifth guard — "engine imported from outside the cut tree" — has no refusing test.** §5.6 says the synthetic-repo harness proves the five orchestration guards; it proves four. The probe lives inside `_verify_suite` (`tools/public_cut.py:377-384`), which the `cut` fixture replaces with a recorder (`tests/contracts/test_public_cut_orchestration.py:63`), the red-suite test replaces with a raising stub (`:122-127`), and the one test calling the real function stubs the probe to return a path INSIDE `verify_dir` (`:164-168`). The refusal at `:383` executes zero times across both public-cut test files. Fix shape: one test with the probe returning the private checkout's `engine/__init__.py`, asserting the named refusal. *Proven:* a line tracer over the real tool during both files (26 passed) shows `:383` hits=0; a mutant with the guard replaced by `if False:` survives all 28 public-cut tests; a scratch test drives the real tool to the refusal. | `tools/public_cut.py:377-384` · `tests/contracts/test_public_cut_orchestration.py:63,122-127,164-168` · §5.6 | **before the next mirror cut** (test-only rider; §5.6's P1-18 line amended) |
| P3-17 | **P1-36's fix has no named test — the answer text on the append-only record is asserted nowhere.** §5.8 lists P1-36 under Group C "each with a named test" and names five files; none touches pings. The fix is real (`answer` rides the pings journal line at `engine/web/pings.py:141-146`, before the mutable-doc write), but `tests/web/test_pings.py:106-150` reads the answer back from the plan/draft envelope, never from the journal. A refactor dropping `answer` from the journal line re-opens the original loss with no red test. Fix shape: one test asserting the answered journal line carries the SME's text and that it survives a failed follow-on plan write. *Proven:* a mutant stripping `answer` from the journal line leaves all 50 tests in the 12 ping-touching files green; a scratch test of the scenario fails under the mutant and passes at HEAD. | `engine/web/pings.py:141-149` · `tests/web/test_pings.py:106-150` · §5.8 | **P27 wave 2** rider (test-only; §5.8's Group C list amended) |

**Closed by P29a (2026-09-11, B131), each with a named test:** **P1-47** + **P1-48** (`tests/kb/test_ingest_scan_set.py` — the scan set is every persisted string through one helper; the CLI door's neutral handle) · **P2-51** + **P2-52** (`evals/anonymization/` cases `anon_043` and `anon_044` under the harness at 44) · **P2-53** (`tests/cli/test_kb_ingest_live.py::test_live_runs_both_readers_through_the_traced_caller`) · **P3-16** (`tests/contracts/test_public_cut_orchestration.py::test_the_import_provenance_probe_refuses_an_outside_engine`). Open: **P3-17** (P27 wave 2). The three amended paragraphs (§5.16 P1-45, §5.6 P1-18) are amended in place above; §5.8 P1-36 waits on P3-17. **Pattern (four of the five gate items):** text reaches a persisted place the scan never sees, or the normalization/variant family misses a spelling the readers will plausibly produce — each a small fix; together a half-day rider with tests, not a phase. **For the pilot:** no effect (synthetic material; none touch drafting, revision, export or share). **For A1:** the line "real corpus ingestion under the anonymization gate" is not honest until P1-47, P1-48, P2-51, P2-52 and P2-53 land. Total tracked: **172**.

### 5.18 Post-P28 delta audit, chunk 2 — leak-paths + eval-harness live arms + assembly write-back (2026-09-06, B125, against `624d6e1`)

*The second chunk (B123 §4): three finders — every path by which buyer or SME text can reach a persisted place outside the pursuit; the live arms of the eval harness and the records they write; the xlsx/docx write-back lanes and their proofs — each raw finding refuted independently and then reproduced at HEAD with real output. Eight raw; seven survived, one refuted (a baseline-lock scope reading that B120 §6 already records as the design). Two are the same family as §5.17's pattern — text reaches a persisted place the scan never sees, this time through opt-in doors the P1-46 fix did not cover; three are the anonymization live arm's RECORD being wrong, stale or crash-prone, and A1's acceptance line rests on that record; two are write-back proofs that exclude the very part they should cover. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-49 | **The two opt-in gap→card doors write the buyer-naming question and the SME's raw answer into the FIRM store's `kb/proposals/` unplaceholdered and unscanned; the P1-46 route then dedupes against them and never re-cleans; steward accept mints a card whose front matter swears it was anonymized.** P28 closed P1-46 on the accept-time route only: `_route_gaps` (`engine/web/learn.py:150-158`) feeds `propose_gap_answer_card` with `{**gap, **cleaned}` after `clean()` and `verify()`. The same spawner has two OPT-IN callers that pass the gap raw — Gate 0 `answers[].propose_card` (`engine/intake/gate.py:168-171`, the answer assigned raw at `:153`) and the ping-answer door `propose_card` (`engine/web/pings.py:166-170`, raw at `:148`, reached from `POST /api/pursuits/{id}/pings/{ping_id}/answer`). `propose_gap_answer_card` (`engine/kb/curation.py:256-263`) writes `gap["question_to_human"]` — model-generated from the buyer package, so it routinely names the buyer — as the proposal title and `Q: …\nA: {answer}` as the body, with neither `apply_placeholders` nor `scan`. The record lands in the firm store (steward inbox, assistant `proposals_queue`, `GET /api/kb/proposals`, the post-purge sweep's texts). Because `_route_gaps` skips any `gap_id` that already has a proposal (`learn.py:147`), the raw proposal is never replaced by the cleaned one. On steward accept, `_check_new_card` stamps `anonymization.status: "anonymized"` unconditionally (`curation.py:326`) — an audit record that lies — and the card enters retrieval for every later pursuit's drafter prompt. B122 §1's "answered gaps pass the same check" holds for one of the three callers. Fix shape: the cleaner+scan moves INTO `propose_gap_answer_card` (one door all three callers must pass), a scan hit refuses the proposal and names the event in the gate/ping record, `_route_gaps` re-checks rather than trusting `already`, and `_check_new_card` derives `anonymization.status` from a scan of the body rather than asserting it. *Proven:* a Gate 0 answer naming the buyer, a contact's email and phone, and a fee, with `propose_card: true`, wrote a proposal whose `scan` returned five findings (CLIENT ×2, FEE, `<contact_info>` ×2); `_route_gaps` afterwards opened nothing and left the file byte-identical; `merge_batch` minted a card carrying the raw strings under `anonymization.status: anonymized`; the ping door reproduced identically with the buyer name in `title.after` as well. | `engine/kb/curation.py:256-263,326` · `engine/intake/gate.py:153,168-171` · `engine/web/pings.py:148,166-170` · `engine/web/learn.py:147` | **pre-A1 rider (proposed P29)** — §5.16's P1-46 line amended to "accept-time route only; the opt-in doors P1-49". Pilot-reachable door, synthetic material until A1 |
| P1-50 | **The anonymization live arm re-runs into a persistent per-case KB store, so the recorded live measure reflects the PREVIOUS run's cards, not the readers under test.** `run_anonymization_set` builds each case's store at `<workdir>/<case_id>/kb` (`engine/kb/evalset.py:280,295`) and never clears it; the CLI live arm defaults the workdir to `pursuits/eval-live/anonymization` and `mkdir(exist_ok=True)`s it (`engine/cli/evals.py:122-123`), and `docs/uat/a1-anonymization-live.md` names the same path and tells the operator to fix the reader and re-run. On the re-run `ingest_document` dedups the fresh candidate against the leftover cards — `card_exists` → skipped (`engine/kb/ingest.py:724-726`), containment → the OLD card survives (`:765-767`) — and `retrievable_text(store)` (`evalset.py:316`) is then read over the old text. `live-record.json` is written with today's `at` and `config_digest` but its pass/fail was decided over cards an earlier reader produced: a leaky run 1 condemns a fixed reader forever, and a clean run 1 can vouch for a reader that regressed. The UAT doc's "every case gets a throwaway store" is false for the live arm — exactly the record A1 cites. Fix shape: the runner wipes (or mints a fresh, timestamped) `<case_id>` directory before each case and the record carries the store path it measured; a test runs the harness twice into one workdir with a leaky then a clean reader and asserts run 2 passes. *Proven:* clean readers into an empty workspace → `ok=True`, one card; that card then salted with a synthetic third-party name; the SAME clean readers into the SAME workspace → `ok=False`, the salted name reported retrievable, the salted card still on disk; the control into a fresh workspace → `ok=True`. | `engine/kb/evalset.py:280,295,316` · `engine/cli/evals.py:122-123` · `docs/uat/a1-anonymization-live.md` | **pre-A1 rider (proposed P29)** — must land BEFORE A1's live run; the UAT doc's re-run step rewritten |
| P2-54 | **The live record's staleness check covers the case list and the committed fixture files only — generator-built cases, the reader prompts, the model pins and the scan code all change without staling it.** `cases_fingerprint` (`engine/kb/evalset.py:207-212`) hashes the cases plus every `input.files` entry that `is_file()` under `evals/anonymization/`; the four generator cases (anon_021/022/041/042, built at run time by `engine/extraction/corpus.py`) contribute only their generator NAME, so editing the builders changes the corpus with the record intact — contradicting the UAT's "stales itself on any corpus edit". `live_measure` (`:248-256`) compares that fingerprint alone: the stored `config_digest` (`:227`) is never read back, and no prompt/model/code fingerprint exists — the locks the poison arm holds by design (`engine/validation/poison.py:176-201`). After A1 records `pass: true`, a prompt hardening, a model-pin change or a scan edit leaves `measures.live = measured / pass: true` citing readers never measured. Fix shape: the fingerprint gains the generator module source, the two reader prompts, the model pins and the gate code (the poison arm's recipe), and `live_measure` refuses `measured` when the stored `config_digest` differs from today's. *Proven:* fingerprint identical before and after a generator edit (38 files hashed, the four generator cases absent); a record whose `config_digest` is all zeros still yields `{'status': 'measured', 'pass': True}`. | `engine/kb/evalset.py:207-212,227,248-256` · `docs/uat/a1-anonymization-live.md` | **pre-A1 rider (proposed P29)** — same commit as P1-50 |
| P2-55 | **The calcChain patch keys on sheet POSITION where ECMA-376 keys on `sheetId`, and does not carry an omitted `i` forward — on a real Excel workbook the write-back either leaves a stale entry for the cell it just made an inline string or re-parents every following implicit entry to the wrong sheet.** `_sheet_index` returns the 1-based position in `workbook.xml` (`engine/assembly/xlsx_patch.py:80`) and `_patch_calc_chain` matches `(int(entry.get("i", "1")), r)` (`:146`); per ECMA-376 18.6.2 `i` is the sheet's `sheetId`, and Excel writes `i` only when the sheet changes (an omitted `i` inherits the previous entry's). A workbook with a deleted middle sheet (sheetIds 1,3 at positions 1,2) or with Excel-style implicit `i` produces either outcome, and both are the "Excel repairs the file on open" result the module docstring says the patch prevents — under the firm's name, on the buyer's form. `assert_roundtrip` excludes `CALC_CHAIN` from every check (`:231`), so the proof passes; every fixture is openpyxl-written (no calcChain, sequential ids), so the suite never exercises either path. Fix shape: `_sheet_index` returns `sheetId`; `_patch_calc_chain` tracks the running `i` and, when it removes an entry that carried one, stamps it onto the next implicit entry; `assert_roundtrip` asserts no calcChain entry names a cell that is now `t="inlineStr"`; two hand-built Excel-shaped fixtures. *Proven:* case A (sheetId 3 at position 2) — output calcChain unchanged while the target cell is `t="inlineStr"`; case B (implicit `i`) — the wrong entry removed and the next one re-parented to sheet 1; `assert_roundtrip` passed both. | `engine/assembly/xlsx_patch.py:80,146,231` | **pre-A1 rider (proposed P29)** — pilot-facing lane; reopen trigger if deferred: the first buyer workbook carrying `xl/calcChain.xml` |
| P2-56 | **A write-back whose round-trip proof FAILS leaves the unproven output on disk; the next `/export` recompose records it as `produced` against the previous confirm's facts.** `run_writeback` writes `exports/writeback/<name>` (`engine/assembly/writeback.py:164`) before `assert_roundtrip` (`:166`) and does not unlink on refusal; `run_docx_writeback` has the same order (`docx_writeback.py:243-244`). The refusal reaches the bundle only for THAT confirm pass via `refusals`; `/export` (`engine/web/server.py:827`) recomposes with none, and `bundle._entry` (`bundle.py:140`) declares `produced` whenever a facts file and an output file both exist — sha256 of the unproven bytes, `revision_n` of the OLD facts. After one good confirm, a later refused confirm yields a downloadable workbook no proof stood behind, listed under `to_the_buyer` with a record that vouches for it. `template_fill.py` already holds the law this breaks ("a stale buyer copy never outlives its facts"). Fix shape: unlink the output (both lanes) before re-raising; `_entry` compares the output's sha256 to the one the facts recorded and reports `drifted` on mismatch. *Proven:* confirm #1 → facts rev 1; the draft revised to hit a shared-formula master; confirm #2 → a drift refusal, no facts, output on disk with a new sha; the export-pass bundle entry: `status: produced`, the new sha, `revision_n: 1`. | `engine/assembly/writeback.py:164-166` · `engine/assembly/docx_writeback.py:243-244` · `engine/assembly/bundle.py:140` · `engine/web/server.py:827` | **pre-A1 rider (proposed P29)** — pilot-facing (export/download); the record-truth half is the P26b-3 bundle's own law |
| P3-18 | **`record_live_result` writes `live-record.json` non-atomically, and a torn record crashes the anonymization lane and the whole `make eval` run instead of reading as `not_measured`.** `Path(path).write_text(json.dumps(...))` (`engine/kb/evalset.py:233-234`) is the one record writer in the P25–P28 delta that bypasses `write_json_atomic` (the P0-6 discipline `cases.write_report` and `remeasure.record_result` adopted); `live_measure` `json.loads` it unguarded (`:248`) and `anonymization_lane` catches only `VacuousMeasure` (`engine/evals/run.py:209ff`), so a Ctrl-C or OOM mid-write leaves a file that takes down every lane's release record on the next run. Fix shape: `write_json_atomic`; an unreadable record yields a typed `not_measured` with the reason. *Proven:* a truncated record → `JSONDecodeError` from `live_measure`, from `anonymization_lane`, and from `run_eval_cli` with zero release records written. | `engine/kb/evalset.py:233-234,248` · `engine/evals/run.py:209` | **pre-A1 rider (proposed P29)** — same commit as P2-54 |
| P3-19 | **`refuse_marked_template` misses tracked changes in footnotes and endnotes.** `inspect_document` scans only parts matching `_DOCX_TEXT_PARTS = ^word/(document|header\d*|footer\d*)\.xml$` (`engine/assembly/hygiene.py:46`, read at `:158-170`); `word/footnotes.xml` and `word/endnotes.xml` are never opened, so a firm template whose only unaccepted `<w:ins>` sits in a footnote passes the P3-15 door, python-docx round-trips the part unchanged, and the mark ships in both the working and the buyer copy under the firm's name. Fix shape: the pattern gains `footnotes|endnotes` (and `comments\d*` for the comment-part count); one fixture with a footnote `<w:ins>`. *Proven:* a template spliced with a footnotes part carrying `<w:ins>` → `revision_marks: {}`, `refuse_marked_template` returned without raising, the buyer copy produced with one `<w:ins>` in its `footnotes.xml`. | `engine/assembly/hygiene.py:46,158-170` | **pre-A1 rider (proposed P29)** — one-line pattern + fixture; P27 wave 2's per-file hygiene line inherits it |

**Refuted (recorded so it is not re-found):** "the baseline lock excludes every `*_fingerprint` key, so a one-file edit to a stored environment fingerprint clears `baseline_stale`" — the mechanics are real, but B120 §6 records the lock's scope as the measures only, with the environment fingerprints verified by recompute; the finder's scenario is the two-file/one-field forgery B120 §6 names as the stated limit. Not a defect; a limit already on the record.

**Closed by P29a (2026-09-11, B131), each with a named test:** **P1-49** (`tests/kb/test_gap_card_one_door.py` — one door for all three callers, the accept-time re-check voids a dirty proposal, a card mints only from a scanned body) · **P1-50** + **P2-54** + **P3-18** (`tests/evals/test_anonymization_live_arm.py` — the rerun into one workdir, the input-naming staleness, the torn record). Open for P29b: **P2-55**, **P2-56**, **P3-19**. §5.16's P1-46 and P1-4 lines are amended in place above. **Pattern:** the same spawner or the same store reached by a second caller the fix did not cover (P1-49, P1-50), and a proof that excludes the very part it should cover (P2-55's calcChain, P2-56's refused output, P3-19's footnotes) — small fixes; the rider grows from half a day to about a day. **For the pilot:** P1-49, P2-55 and P2-56 are pilot-reachable doors (Gate 0 answers, ping answers, form write-back and export), but the pilot's material is synthetic, so the consequence there is a wrong record, not a leak of real material; no pilot action before P29. **For A1:** the live anonymization record — A1's acceptance line — is not trustworthy until P1-50, P2-54 and P3-18 land, and the "real corpus ingestion under the anonymization gate" line now also waits on P1-49. Total tracked: **179**.

### 5.19 Post-P28 delta audit, chunk 3a — web doors + auth, crash safety + locks (2026-09-06, B126, against `97cc60c`)

*The third chunk's first half (B123 §4, two finders per run from B125 §5): every operator and guest door in the delta, and the crash-convergence law across the contracts/workspace/runlog/pipeline changes. Seven raw, seven survived (each refuted independently and reproduced at HEAD with real output), merged into five rows: the two torn-lane findings are one defect (B106 §1's claim not delivered in two lanes), the two reserved-filename collisions are one defect (no reserved-name refusal at an upload door). None already on the register; the closures they qualify (P1-17, P2-20, P0-13, P1-22) are cited, not reopened. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-51 | **The jobs journal's torn-tail recovery manufactures the corruption it refuses: `_rehydrate` tolerates a torn final line, then appends onto it, and the SECOND restart raises `ContractError` out of `JobRunner.__init__` — the server cannot start until the journal is hand-repaired.** `_rehydrate` reads the journal through the tolerant reader and records `journal_torn` (`engine/web/jobs.py:76-77`) but never truncates the fragment — unlike `RunLogger(resume=True)`, which truncates at `torn_tail_offset` before writing (`engine/runlog/writer.py:116-125`). It then re-journals each orphaned job via `self._journal` → `append_fsync` (`jobs.py:96`, `:70`), and `append_fsync` writes `line + "\n"` without checking the file's tail (`engine/contracts/atomic.py:54-58`), so the orphan record is concatenated onto the unterminated fragment. That merged line is newline-terminated and NON-final — exactly the shape B106 §1 defines as corruption; the next restart fails in `__init__`. The same happens with no orphans at all: any later `submit`/`_finish` write lands on the fragment. The recovery path corrupts the audit record on the documented crash case, and `test_rehydrate_closes_orphaned_runs_and_tolerates_a_torn_journal_tail` restarts only once so never sees it. Fix shape: `_rehydrate` truncates at `torn_tail_offset` before its first write (the writer.py discipline, one home), or `append_fsync` itself guarantees a newline precedes every append; the test restarts twice. *Proven:* torn tail → restart 1 sets `journal_torn`, the journal now holds the fragment fused to the orphan record; restart 2 → `ContractError: jobs.jsonl: line 2 is not a JSON record … — this is corruption`, exit 2; the no-orphan/one-submit variant fails identically. | `engine/web/jobs.py:76-77,96,70` · `engine/contracts/atomic.py:54-58` · `engine/runlog/writer.py:116-125` (the correct pattern) | **pre-A1 rider (proposed P29)** — same commit as P3-20; §5.8's "jobs journal tolerates a torn tail" line amended to "tolerates on read, corrupts on write until P1-51" |
| P2-57 | **B106 §1 says the events lane and share links fold through `read_jsonl`; neither does — a torn tail in `events.jsonl` wedges every feedback door and the revise round for that pursuit, and a torn tail in ONE pursuit's `share/links.jsonl` 500s every guest route for ALL pursuits plus that pursuit's revoke kill switch.** `EventsLane.read` json-loads every line raw (`engine/web/events.py:73`); `append` calls `read` under `_APPEND_LOCK` to mint the next id (`:115-116`), so a crash mid-append turns POST `/outcome`, `/effort`, `/events`, `/accept`, `/waivers` and GET `/comments` into 500s, and `finalized_by_cid` (`:133`) / `latest_outcome` (`:229`) raise into the revise round — no round can commit until someone hand-truncates the file. `ShareLane._folded` does the same (`engine/web/share.py:67`), and `_resolve_share` walks EVERY pursuit's `links.jsonl` on every guest request (`server.py:1141-1151`), so one torn line anywhere in the workspace 500s GET `/share/{token}` and POST `/share/{token}/comments` for every guest, while `revoke` (`share.py:106`) and `create` (`:96`) 500 for the torn pursuit — a link that must be killed stays live. Only `jobs.py:76` and `pings.py:54` call `read_jsonl`; B106 §1 claims four lanes. The run-log lane has a repair door and an honest report for this condition; these two have neither. Fix shape: both lanes read through `read_jsonl`, the torn tail is truncated under the lane's lock before the next append (P1-51's rule), the torn report surfaces; `_resolve_share` treats one pursuit's unreadable lane as that pursuit's problem, not every guest's. *Proven:* events — `/outcome` and `/comments` 200 before the tear, 500 after, `read_jsonl` on the same file returns 1 record + a named torn tail; share — a guest on a second pursuit gets 500 on view and comment after the first pursuit's tail is torn; the torn pursuit's revoke/create/list all 500. | `engine/web/events.py:73,115-116,133,229` · `engine/web/share.py:62-69,96,106` · `engine/web/server.py:1141-1151` · DECISIONS.md B106 §1 (the claim) | **pre-A1 rider (proposed P29)** — same commit as P1-51; B106 §1's lane list corrected in the same commit |
| P2-58 | **Share-link revoke — the P9 kill switch — is refused with 409 for the whole duration of any job on the pursuit, and the guest keeps reading the draft meanwhile.** B104 §5 closed P0-13's residual by moving `revoke_share` under `_mutate` (`engine/web/server.py:1130-1138`), but `_mutate`'s first act is a 409 whenever `runner.busy(pursuit_id)` is truthy (`:1828-1843`) — before the guard is taken. No job reads or writes `share/`; `revoke` appends one last-wins line (`share.py:105-112`); the serialization it bought is against `create`, not the runner. So during an advance or revise (minutes with live calls) the operator's revoke returns "… running — decide after it finishes", the link stays resolvable, and the one guest-access control is unavailable exactly when a draft is changing. `test_revoke_is_the_kill_switch` never runs against a busy pursuit. Fix shape: the share lane takes the pursuit guard without the busy refusal (a guard-only context, or the lane's own append lock as `EventsLane` has), keeping P0-13's mint serialization; the kill-switch test adds a busy-pursuit case. *Proven:* valid link, a running revise job → revoke 409, `links.jsonl` unchanged, guest GET 200; after the job ends, revoke 200 → guest GET 410. | `engine/web/server.py:1130-1138,1828-1843` · `engine/web/share.py:105-112` · `tests/web/test_share.py` (the missing case) | **pre-A1 rider (proposed P29)** — pilot-reachable door; §5.7's P0-13 closure line gains "revoke is serialized but not job-blocked (P2-58)" |
| P3-20 | **A final record persisted WITHOUT its trailing newline parses cleanly, so `read_jsonl` reports no torn tail, the resumed writer appends straight after the closing brace, and two records merge into one line every later read classes as corruption.** The torn-tail check at `engine/contracts/jsonl.py:35` lives inside the `except JSONDecodeError` branch only; a crash that persists the full object but drops the final byte yields `torn=None`, `RunLogger(resume=True)` skips the truncate (`writer.py:116`), and `emit` appends `json.dumps(record)+"\n"` unchecked (`writer.py:183-184`) — as does `append_fsync` (`atomic.py:54-58`) for the jobs journal, events, pings and share. The run's `run_end` lands as `{…}{…}`; `read_run`, the board and the metrics walker then raise `ContractError … (Extra data) — this is corruption`, and the repair is not on the record. Narrower than P1-51 (a specific tail shape) but the same root: no writer checks that the file ends in a newline before appending. Fix shape: one rule in `append_fsync` and `emit` — if the file is non-empty and its last byte is not `\n`, write the newline first (and log it as a repaired tail); `read_jsonl` reports a parseable-but-unterminated final line as a torn tail by the same name. *Proven:* strip the final newline from a two-line run, resume → `read_jsonl` records 2, torn None; `run_end` written; `read_run` → `ContractError … line 2 is not a JSON record (Extra data)`. | `engine/contracts/jsonl.py:35` · `engine/runlog/writer.py:116,183-184` · `engine/contracts/atomic.py:54-58` | **pre-A1 rider (proposed P29)** — same commit as P1-51 (one tail-newline rule closes both) |
| P3-21 | **Two upload doors accept a lane's reserved filename: `inbox/roles.json` is overwritten by the upload body, and an addendum named `meta.json` is lost while its record says `scanned: true`.** The inbox door refuses only path traversal (`clean = Path(filename).name`, `server.py:286-289`) and then `write_bytes_atomic(root/"inbox"/clean, body)` (`:302`); with `?role=` the RMW that follows json-loads the just-written body and 500s (`:305-306`), leaving the B67 §3 declared-roles record holding document bytes — every declared role is gone and the next advance job's `_resolve_targets` lands in `error`; without `?role=` a valid-JSON body silently replaces the record with roles outside the `core|supplemental|target` check. `AddendumLane.store` writes the upload to `addenda/addm_NN/<filename>` (`engine/web/addenda.py:71-73`) and then its own `meta.json` into the same folder (`:86`); `server.py:768` passes `Path(filename).name` with no reserved-name check, so `filename=meta.json` (and the replan archive names overwritten at `:164`) collide — the buyer amendment's bytes are gone, the lane's stated human fallback ("reads it directly") has nothing to read, and the record attests a stored file that does not exist. Fix shape: each lane owns a reserved-name set and the door refuses with a typed 400 (the traversal refusal's twin); one test per door, proven red first. Operator-facing doors, so P3 — a mistake, not an attack, but a record that lies. *Proven:* `PUT inbox/roles.json?role=core` → 500 and `roles.json` now holds the upload body, the advance job ends in `error`; `PUT inbox/roles.json` (no role) → 200 and the roles record is replaced; `POST addenda?filename=meta.json` → 200 `{filename: "meta.json", scanned: true}`, the folder holds only the lane's own `meta.json`. | `engine/web/server.py:286-308,325-327,768` · `engine/web/addenda.py:71-73,86,164` | **pre-A1 rider (proposed P29)** — pilot-reachable, operator-only doors; related: P1-22 (the roles.json RMW is now under `_mutate`; this is the name, not the lock) |

**Cleared (the finders' own lists, so the next reader does not re-check them):** P0-11/M-9 (client `at`/`actor_role` refused on every operator door that records one), P0-18 (both guest routes use `now()`), P0-19/P0-21 (the review operator-gated; the guest strip removes identities, waivers, reasons, red-team, pending), P0-7 (TrustedHost + headers middleware outermost, cross-site refusal, SameSite cookie), P0-8 (streamed caps with a Content-Length pre-check on all three raw-body doors), P2-16/P2-17/P3-14, the job worker's typed lanes and cancel states; gate-key convergence at all three gates, `read_frozen` at every authoritative frozen read, `mint_run_id` max+1 with the existing-run refusal at every construction site, the org store atomic under a mint lock, the CLI's `serve.lock` on intake/slice/kb-purge, the directory-fsync park (SESSION.md). Below the finding bar, recorded: `_resolve_share` pre-scans tokens with `==` before `compare_digest` (negligible over loopback); a guest comment during a job gets `_mutate`'s 409 naming the job id.

**Closure paragraphs to amend when the rider lands (no ids change):** §5.8 P2-20/P1-17 → "the jobs journal tolerates a torn tail on read; the write side P1-51/P3-20" · §5.7 P0-13 → "revoke serialized but not job-blocked (P2-58)" · DECISIONS.md B106 §1's lane list → the two lanes that actually fold (P2-57). **Pattern:** B106 §1 wrote one tolerant-read rule, but only the run-log lane got the matching write-side discipline (truncate before append); the jobs, events and share lanes got the claim without the code, and no writer anywhere checks the tail before appending. **For the pilot:** every door here is pilot-reachable (feedback events, guest share, revoke, inbox and addenda uploads) but each needs a real crash mid-append or an operator naming a reserved file; the exposure is a wedged pursuit or a lying record, not a leak — no pilot action before P29, but the pilot host should know that a torn `events.jsonl`/`links.jsonl`/`jobs.jsonl` today is a hand-truncate, and that revoke waits for a running job. **For A1:** the anonymization record and the ingestion gate are untouched; A1's restart-safety claim (crash → restart → continue) is not honest until P1-51 lands. Total tracked: **184**.

### 5.20 Post-P28 delta audit, chunk 3b — flywheel-learn + purge/provenance/retrieve (2026-09-06, B127, against `94528e7`)

*The third chunk's second half (B123 §4): two finders — the learn side of the flywheel (proposal merge, the curation log, the assistant's read-only registry) and the purge closure across provenance, proposals and retrieval withholding. Five raw; four survived, one refuted (a granted `purge_org` losing its authorizing access-log line — real only under a parameterization no production caller uses; `purge_org` has no CLI or web door, the org UI is B75 §5's A6 deferral, and the firm-store sweep line is the durable record). One survivor is entered a class below the finder's severity on the correctness refuter's dissent, recorded under its row. No merges. None already on the register; the closures they qualify (P2-46, P1-43, P1-21/P1-40, B117 §6's sweep limit) are cited, not reopened. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-52 | **`purge_client` leaves the claim-promotion `new_card` proposal derived from the purged client in the inbox; a later steward accept re-mints the client's material into the firm KB, and a second purge finds nothing — the purge guarantee is breakable by the ordinary steward loop.** The closure walks restricted provenance records only (`engine/kb/purge.py:63-85`), and the post-purge sweep (`purge.py:112-126`) scans proposals for purged identifier STRINGS and checks only that purged CARDS are gone — `diff.derived_from` is never consulted. But every claim candidate the ingest opens is exactly a `new_card` proposal whose `diff.derived_from` names the chunk card (`engine/kb/ingest.py:836-837`; the design comment relies on that link for the purge cascade). After the purge the proposal sits `proposed` with its target gone; `_apply_new_card` (`engine/kb/curation.py:292-297`) writes the card with `provenance.sources: [{source_pursuit}]`, no `source_client`, and `derived_from` pointing at a record that no longer exists — no existence check on the targets. A second `purge_client` for the same client walks no provenance record naming it and reports CLEAN. B117 §6's "the widened sweep names any survivor" holds for strings, not for lineage; the material is placeholdered claim text, so P1 not P0 — but it is permanently unpurgeable, which is the A1 governance precondition (B91 §3) failing by construction. Fix shape: the closure follows `derived_from` INTO the proposal store (a proposal whose targets include a purged card is voided with a curation-log line naming the purge, the way P0-16's addendum-void records itself); `_apply_new_card` refuses when any `derived_from` target does not exist; the sweep reports any proposal still naming a purged `kb_id`. *Proven:* ingest → a `proposed` claim proposal derived from the chunk card; purge 1 → the card purged, `sweep_clean: True`, the proposal survives; accept → a new fact card with `derived_from` naming a card that no longer exists and a placeholdered body from the purged client's document; purge 2 → `purged: []`, `sweep_clean: True`, the card still on disk. | `engine/kb/purge.py:63-85,112-126` · `engine/kb/ingest.py:836-837` · `engine/kb/curation.py:292-297` | **pre-A1 rider (proposed P29)** — the purge guarantee is A1's named precondition; §5.13's B117 §6 limit line amended to "names any surviving STRING; lineage survivors P1-52" |
| P2-59 | **A retained `.src` with no meta — the `write_source` crash window — is invisible to `source_metas`, so the client's raw un-anonymized bytes survive `purge_client` and the report says CLEAN; no later purge can ever find them.** `write_source` is two atomic writes (`engine/kb/provenance.py:131-132`: the bytes, then the meta); a crash between them leaves `<doc>.src` without `<doc>.json`. The P2-46 rewrite of the purge's L0 walk switched from `list_source_ids()` + `source_meta()` — which raised on the orphan and failed the purge LOUDLY — to `source_metas()`, which drops any `.src` lacking a meta (`provenance.py:153-156`), while `list_source_ids` (`:164-168`) still lists it. `purge_client`'s `direct_cds` (`engine/kb/purge.py:227-231`) is built from `source_metas`, so the orphan is never named; the sweep scans cards and proposals only; `l0_sources: []`, `swept_clean: True`, and the raw text remains in the restricted store — precisely the blocked-ingest case that minted no cards and relies entirely on this walk. Narrow window, real bytes, a lying record: P2. Fix shape: `source_metas` (or a purge-side `orphan_sources`) reports every `.src` without a meta by name; `purge_client` treats an orphan as a finding ("retained source has no meta — cannot attribute, not clean") rather than silently clean, with the disposition named in the runbook; `write_source` writes the meta FIRST so a crash leaves a meta with no bytes (harmless) rather than bytes with no meta. *Proven:* control (meta written) → `l0_sources=['cd_…']`, `.src` gone after purge; crash-window (the meta write made to raise) → `list_source_ids` names the id, `source_metas` is empty, `swept_clean=True l0_sources=[]`, the `.src` still on disk with the synthetic client text. | `engine/kb/provenance.py:131-132,153-156,164-168` · `engine/kb/purge.py:227-231` · `tests/kb/test_purge.py` (the blocked-ingest case this walk carries) | **pre-A1 rider (proposed P29)** — same commit as P1-52 (one purge-closure pass); §5.12's P2-46 line amended to "the doors log and authorize; the walk's orphan blindness P2-59" |
| P2-60 | **The assistant's `card_detail` tool hands the model the full body of a `use_restriction` (D2) or deprecated card that its sibling `open_card` refuses, emits no `kb_retrieval` line, and grants citation right — one withholding predicate applied at one of two doors in the same registry.** `_t_open_card` routes through `targeted_open`, whose withholding (`engine/kb/retrieve.py:313-325`) refuses D2 and deprecated cards with the refusal on the trace — proven for `open_card` only (`tests/assistant/test_tools.py:68-74`). `_t_card_detail` (`engine/assistant/tools.py:151-160`) calls `curation.card_detail`, which returns `body` unconditionally (`engine/kb/curation.py:109,134` — its consumer is the steward's curation screen, where seeing the body is the point), then adds the kb_id to `ctx.opened_cards`, the earned-citation vocabulary. **Entered at P2, not the finder's P1, on the correctness refuter's dissent (recorded):** D2 is defined as a RETRIEVAL control (`schemas/kb-card.schema.json`, B12: "honored at retrieval"), every assistant route is operator-only, the operator can open the same body on the curation screen and via `GET /api/kb/cards/{id}`, and the run log carries a `tool_call` line with digests for the read (`engine/assistant/loop.py:172-174`) — no person-boundary is crossed and the trace does not lie, it lacks the `kb_retrieval` vocabulary. What stands: the model's context receives what retrieval withholds, and a citation of that card passes the cite guard through a door that never withheld — the P14 UAT gate's D2 line is proven at one of two doors. Fix shape: the retrieval predicate applied at the assistant boundary — `_t_card_detail` refuses by the same name and emits the same refusal line as `open_card` (the steward's web route keeps the unwithheld view); `opened_cards` gains an id only through a door that withholds; the named test gains `card_detail` as a second parametrized door. *Proven:* `open_card` on the restricted card refused with the trace line; `card_detail` on the same card → the body returned, `opened_cards` gains it, no `kb_retrieval` line; identical for the deprecated card. | `engine/assistant/tools.py:151-160` · `engine/kb/curation.py:109,134` · `engine/kb/retrieve.py:313-325` (the control) · `tests/assistant/test_tools.py:68-74` (the one-door proof) | **pre-A1 rider (proposed P29)** — two lines plus a parametrized test; §5.13's P1-43 line amended to "withheld from `open_card` and retrieval; `card_detail` P2-60" |
| P3-22 | **A repeated `proposal_id` inside one merge batch records a fully-applied merge as `aborted` in the curation log and 500s the steward.** Pass 1 of `_merge_batch_locked` (`engine/kb/curation.py:470-479`) reads each id's status without deduping `proposal_ids`, so both entries see `proposed`; pass 2 (`:513-529`) applies and decides on the first, then `proposals.decide` raises `ProposalStateError` (`engine/flywheel/proposals.py:142-145`) on the second; the `except BaseException` sets `aborted` and the `finally` writes the log line (`:531-538`) with `"aborted": "ProposalStateError: … already accepted"` — the record says the batch failed mid-way when nothing failed to apply (`append_lesson` is idempotent; the proposal is `accepted`). `kb_merge` (`engine/web/server.py:687-699`) catches `CurationRefused` and `ContractError` only, so the route returns 500; for a `new_card` proposal the second pass hits the "already exists" refusal instead — a 409 for a merge that succeeded. P1-21's atomicity and P1-40's exclusion both hold; this is the batch's input contract, and a record that lies about a success. Fix shape: pass 1 refuses a duplicate id by name (`CurationRefused`, 409) before anything is applied; `kb_merge` maps `ProposalStateError` to 409 (the `/decide` route already does — the two doors are inconsistent). *Proven:* `merge_batch(ids=[p, p])` → `ProposalStateError`, lessons on the card 1, proposal `accepted`, the log line carrying `aborted`; through the route → HTTP 500, same log shape. | `engine/kb/curation.py:470-479,513-538` · `engine/flywheel/proposals.py:142-145` · `engine/web/server.py:687-699` | **pre-A1 rider (proposed P29)** — one refusal + one exception mapping; steward-facing door, pilot-reachable |

**Refuted (recorded so it is not re-found):** "a granted `purge_org` destroys the access-log line that authorized it" — reproducible only with `firm_store=None`, which no production path passes; with the firm store the sweep line (`purge.py:472-475` → `log_sweep`) is written to the FIRM store's `access.jsonl` after the delete, outside the destroyed tree. Recorded beside it: `purge_org` and `purge_pursuit_memory` have no engine, web or CLI caller today (only `purge_client` is wired, via `rfp kb purge`); the org UI is B75 §5's A6 deferral — a library-level audit gap until A6, not a defect.

**Cleared (the finders' own lists):** the unconditional lane authorize (P1-13) fires on empty pursuit and org lanes and logs before any delete; every L0 read door and `absorbed_owners` log-then-authorize (P2-46); `card_search` withholds deprecated cards before idf, exclude is post-idf (M-29); `descend` withholds a restricted/deprecated anchor and its neighbours (M-28); `DeprecatedCard` is a `UseRestrictedCard` subclass so existing D2 catch sites cover it; `strip_carried_forward` re-reads the filesystem and lessons carry `proposal_id`; the org id mint is max+1 under a lock; `learn_from_writeback`'s proposal titles come from the firm's own bundled template, not buyer prose; `_route_waiver`'s partial-open-then-block is reachable only through B117 §6's stated waiver-join limit; the opt-in gap→card doors were seen and NOT re-reported (open row P1-49).

**Closure paragraphs to amend when the rider lands (no ids change):** §5.13 B117 §6 sweep limit → "names any surviving string; lineage survivors P1-52" · §5.13 P1-43 → "withheld from `open_card` and retrieval; `card_detail` P2-60" · §5.12 P2-46 → "the L0 doors log and authorize; the walk's orphan blindness P2-59" · §5.12 P1-21/P1-40 → "atomic and exclusive within a batch; the duplicate-id input P3-22". **Pattern:** the same as §5.18/§5.19 — a control built at one door that a sibling door or the same walk does not carry: the purge cascades over `derived_from` on cards but not on the proposals the ingest opens by that very link (P1-52); the P2-46 door rewrite made the walk quieter than the one it replaced (P2-59); `open_card` withholds but `card_detail` does not (P2-60). The rider's one-line rule for this family: **a withholding or purge control is proven at every door that reads the store, not the first one built.** **For the pilot:** P2-60 and P3-22 are pilot-reachable (the steward assistant and the merge door) but the pilot KB is synthetic, so the consequence is a wrong trace vocabulary or a lying log line, not a leak; P1-52 and P2-59 need a purge, which the pilot does not exercise. No pilot action before P29. **For A1:** the purge guarantee — B91 §3's named precondition for real client material — is not honest until P1-52 and P2-59 land; the P14 assistant UAT gate's D2 line is proven at one of two doors until P2-60 lands. P29 grows by about half a day. Total tracked: **188**.

### 5.21 Post-P28 delta audit, chunk 4 — pipeline stages + the caller seam, the public cut (2026-09-10, B128, against `d888731`) — THE AUDIT CLOSES

*The last chunk (B123 §4): two finders — the stages, the caller seam and the metrics; the public-cut tool and CI — each raw finding refuted independently and reproduced at HEAD. Two raw, two survived (the P1 on 3 of 3), none refuted, none already on the register. The pipeline finder cleared the live caller's transient classification, the handoff caller, the budget arithmetic, the walker keying, the P0-15/P1-33/P1-34 resolvers against their writers, the docker backend, the xlsx hidden-column path, the checkpoint bindings, research's Gate-1 refusal and the slice's `--fresh` lock. The public-cut finder cleared manifest/deny coverage (pathspec semantics match `git archive`), release-mode deletion guards and neutral identity, every shipped docx/xlsx's creator and zip members, the staging suite's import provenance, and both CI SHA pins against their tags. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P1-53 | **The revision round's replayed commit writes a round record that says the round consumed nothing — the P1-14 resume path rebuilds `consumed_ids` by filtering the finalized events on the PRIOR revision, but every event this round finalized is stamped with the NEW one.** `run_round` rewrites `drafts/draft.json` with `revision_n = round_n` before the finalize loop (`engine/revision/round.py:427-435`), and each `lane.append` (`round.py:533`) stamps `revision` from `EventsLane.current_revision()`, which reads that file (`engine/web/events.py:97-119`) — so the finalized comments and edits carry `round_n`. A crash after `lane.drop_pending` (`round.py:561`) and before the record write (`:612`) makes the next call resume (`draft_sha256_out` matches, `resume_commit=True`, zero spend) and rebuild from `already.values()` with the predicate `e.get("revision") == prior_n` (`round.py:562-568`, `prior_n = round_n - 1` at `:419`) — which matches nothing this round finalized. `revisions/round_N.json`, the D6 audit record of the round, lands with `consumed_event_ids {internal: [], external: []}`, `dismissed_external_event_ids []` and `external_screen_flags []` while `events.jsonl` holds the same cids finalized at revision N; an included external comment's injection-screen flags (the D16c trace) vanish from the record with them. For round 2 and later the same predicate matches the PREVIOUS round's events, so a replayed record misattributes rather than merely omits. Status reads `complete`. `tests/revision/test_round_crash.py`'s `after_drop_pending` case asserts only `to_revision == 1`, so the P26a closure passed over it. Fix shape: derive the consumed set from the cids the round's own annotated rebuild names (so the predicate does not depend on the stamp at all), or filter on `round_n`; the crash test asserts the record's three id lists equal the control run's. *Proven:* killing after `drop_pending` and replaying → `status: complete`, `events.jsonl` holds two comments finalized at revision 1, `round_1.json` `consumed_event_ids {'external': [], 'internal': []}`; the same fixture without the crash records both ids. | `engine/revision/round.py:419,427-435,533,561-568,612` · `engine/web/events.py:97-119` · `tests/revision/test_round_crash.py` | **pre-A1 rider (proposed P29)** — the crash-safety tail beside P1-51/P2-57; §5.8's Group B line amended to "P1-14: the commit resumes; its record is empty until P1-53". Pilot-reachable: any review round that dies in the commit window |
| P2-61 | **The residue scan never reads a symlink's own bytes — a tracked symlink would ship its link text (an absolute path carrying a username, say) to the mirror unscanned, and a dangling one also trips the deletion guard as a false "surprise".** `residue_offenders` admits staged entries with `path.is_file()` (`tools/public_cut.py:135`) and scans `path.read_bytes()` (`:150`); both follow the link, so what git stores for a mode-`120000` blob — the target path — is never matched against the baseline or the machine-local patterns. A dangling link is skipped outright; a live one has its TARGET's content scanned in place of its own. `git archive | tar` recreates tracked symlinks in staging and `git add -A` commits them as `120000` blobs, so the link text reaches the public repo while the scan reports clean and the suite stays green. Secondary: `staged_paths` (`:266-268`) drops dangling links the same way, so a shipped one is in `published − staged` at the next release and `release_commit` refuses it as an unacknowledged deletion though it is still in the cut. The docstring's "sweeps every staged file — contents, filenames" is not met for this file kind. **Not a current leak:** v2 tracks no symlink at HEAD (`git ls-files -s` has no `120000` entry); it is a blind spot the first `git add` of a symlink opens. Fix shape: the cut refuses any `120000` entry in the export — simplest, and in keeping with the mirror's review-only posture; a test stages a dangling link whose text carries a residue pattern and asserts the refusal. *Proven:* a staging tree with a dangling link whose text alone carried a person-shaped path and a live link gave `residue_offenders → []`, `staged_paths` omitting the dangling one, and the cut commit's `120000` blob reading back as the link text. | `tools/public_cut.py:14-19,134-135,150,266-268` · `tests/contracts/test_public_cut.py` | **CLOSED by P29a (2026-09-11, B131)** — `tests/contracts/test_public_cut_orchestration.py::test_a_tracked_symlink_refuses_the_cut_before_any_export`; the live-repo pin `test_public_cut.py::test_the_private_tree_tracks_no_symlink` is the reopen trigger, enforced |

**Below the finding bar, recorded so they are not silent (the pipeline finder's notes):** on an after-envelope crash replay, an included external comment with screen flags re-emits its `injection_screen` validation line in the second run (a duplicate line on a crash edge); `fresh_is_safe` calls `iterdir()` on the resolved `--workspace` path without checking it is a directory (a file at that path tracebacks instead of refusing). Both are next-touch items on their files.

**The audit, closed (B128).** Four chunks, six runs (two resumed after the account's usage limit, one relaunched), thirty raw findings, twenty-seven survived adversarial verification, two refuted on the record, one entered a class below its finder's severity on a recorded dissent, merged into **twenty-five register rows: 7 × P1, 11 × P2, 7 × P3, 0 × P0** — P1-47 … P1-53, P2-51 … P2-61, P3-16 … P3-22. Every closure claimed in §5.6–§5.16 was checked against its named test; four were closure-strength gaps (P2-53, P3-16, P3-17, and the P1-14 record P1-53) and the rest held. **One pattern under twenty of the twenty-five:** a control built at one door that a sibling door, a second caller, or the same walk does not carry — the scan over a curated list of strings rather than every persisted string; the tolerant read with no write-side discipline; the cleaner on one of three callers; the withholding at one of two tools; the purge cascade over cards but not the proposals that cite them. **The P29 rider (proposed, the owner's call) carries twenty-four of the twenty-five** (P3-17 rides P27 wave 2) and its acceptance criterion is the pattern's inverse: *a control is proven at every door that reads or writes the store, not the first one built.* **A1 waits on P29 for four of its lines** — real-corpus ingestion (P1-47/P1-49), the live anonymization record (P1-50/P2-54), restart safety (P1-51/P1-53), the purge guarantee (P1-52/P2-59). **The pilot needs nothing before P29:** its material is synthetic; every pilot-reachable door here yields a wrong record or a wedged pursuit under a crash, never a leak of real material. Total tracked: **190**.

### 5.22 Post-P28 delta audit, chunk 5 — shipped-doc claims vs code (2026-09-10, B129) — the lens the design owed

*The one lens of B123 §4's design that had not run as an agent: every control or guarantee a SHIPPED prose doc states about behaviour changed in `626522a..HEAD`, checked against the code and its test (B122 §9's hand sweep had covered P28's docs only). One finder; two raw, two survived (refuter AND reproducer), none refuted. The finder checked and CLEARED: the share-link 30-day cap and guest stripping, accept refusing on `packaging.blocked`, gate effort recorded after the decision, ping escalation on the server clock, `ingest --live`'s refusal / budget / L0-retained-before-scan / no cards or model on block / residue to stderr only, the anonymization live-arm refusals, the baseline lock and rate floors, the remeasure live gating, the run log's torn-tail truncate-on-resume, the board's per-row `corrupt`, rehydrate closing crashed runs, purge lane authorization, deprecated cards withheld from retrieval, card lessons never drafted from. Seven apparent divergences were already open rows (P1-50, P1-51, P2-56, P2-57, P3-18, P3-19, P3-20) and were not re-reported. Ids remain permanent labels; nothing here renumbers.*

| id | finding | where | home |
|---|---|---|---|
| P2-62 | **The runbook's recovery step for an unreadable `drafts/annotated-draft.json` does not exist — the next Advance raises `JSONDecodeError` out of the driver, the job lane records `error`, validation never re-runs and the corrupt file stays; the pursuit is wedged until someone hand-deletes a file the runbook says never needs deleting.** `docs/pilot/runbook.md:140-142` promises that when the board's row says `corrupt` and names this file, "the next **Advance** re-runs validation and rewrites it (the annotated draft is rebuilt, never patched)". The board half is true (`engine/web/state.py:33-41`); the recovery half is not. `validation_is_current` (`engine/pipeline/driver.py:165-174`) checks only `.exists()` and then calls `pursuit.read_artifact(...)`, a bare `json.loads` (`engine/workspace/pursuit.py:111-112`); a truncated file raises out of `advance()` at `driver.py:352` with no guard, and `engine/web/jobs.py:186-187` turns the exception into `state=error`. Every subsequent Advance fails identically — the "rebuilt, never patched" design holds only for a MISSING file, not an unreadable one, which is exactly the crash-and-disk-fault case the paragraph exists for. A wedged pursuit and a runbook that misdirects the operator, no material lost: P2. Fix shape: `validation_is_current` treats an unreadable annotated draft as "not current" (a tolerant read that names the file in the run log — the P1-8 read-side pattern), so the stage rebuilds it and the runbook keeps its promise; a test corrupts the file, presses Advance, asserts validation re-ran and the file is well-formed. The doc-only alternative (tell the operator to delete the file) is the weaker close and contradicts the principle the paragraph cites. *Proven:* a pursuit at gate 2 with a truncated annotated draft → `board()` row `corrupt` naming the file, `validation_is_current` and `advance()` both raise `JSONDecodeError`, the job lane classes it `error`, the file byte-for-byte unchanged after the attempt. | `engine/pipeline/driver.py:165-174,352` · `engine/workspace/pursuit.py:111-112` · `engine/web/jobs.py:186-187` · `docs/pilot/runbook.md:140-142` | **P29 rider — the crash-safety tail** (beside P1-51/P2-57/P1-53; admitted after B128 declared the scope final, B129 §3). Pilot-reachable: any crash or disk fault in the validation window, on synthetic material |
| P3-23 | **The maintenance guide says both flywheel responses list identifier residue under `blocked` by location; only the accept response does — the write-back response folds the refusal into `skipped[slot_id]` as prose, shape-identical to the benign "no values entered" skip, with no `blocked` key.** `docs/steward/maintenance-guide.md:79-82`: a hand-typed case block that still names a party "is not proposed — the accept and writeback responses list it under `blocked` by location (P1-46)". `learn_from_accept` honours it (`engine/web/learn.py:233-242`); `learn_from_writeback` does not — the residue branch (`learn.py:294-300`) writes `skipped[slot_id] = "identifier residue at … — not proposed"` and returns `{"proposals", "skipped"}` (`:320`), passed through verbatim by the confirm route (`engine/web/server.py:1017-1025`). The refusal itself is correct — P1-46's control holds on this door; what fails is the RECORD of it: a reader looking for the key the guide names sees nothing refused, and the residue event is indistinguishable in shape from a routine skip. B122 §9's own doc-sync note called the guide's sentence "accurate as written"; it was accurate for one door of two. Fix shape: `learn_from_writeback` returns `blocked: [{slot_id, locations}]` in the accept response's shape and keeps `skipped` for benign skips; `tests/flywheel/test_proposal_leak_scan.py` gains a write-back case asserting the `blocked` entry by location. *Proven:* a hand-filled case block naming a party, confirmed through the write-back route → `{"proposals": [], "skipped": {"…": "identifier residue at body — not proposed", …}}`, no `blocked` key. | `engine/web/learn.py:294-300,320` (contrast `:233-242`) · `engine/web/server.py:1017-1025` · `docs/steward/maintenance-guide.md:79-82` | **CLOSED by P29a (2026-09-11, B131)** — `tests/flywheel/test_proposal_leak_scan.py::test_writeback_residue_is_listed_under_blocked_by_location` |

**Below the finding bar, recorded so it is not silent:** `docs/steward/steward-runbook.md`'s "Purging a pursuit removes what that pursuit taught — its proposals and the lessons they landed" describes `purge_pursuit_memory`, a library function with no CLI or web door (test callers only; `kb purge --client` does not strip carried-forward proposals — that half is P1-52). The sentence describes a capability a steward cannot invoke; it is reworded to name the door that exists (or the A6 home of the one that does not) at the next touch of the runbook — P29's docs commit, since the runbook is touched there for P1-47.

**The audit, closed for the second and last time (B129).** With chunk 5 the design of B123 §4 has run in full: eleven surfaces plus the closure-claims and docs-vs-code lenses (the `ui-scripts` lens retired into the P27 wave 2 smoke test). Final totals: **32 raw findings, 29 survived, 2 refuted on the record, 1 downgraded on a recorded dissent, 27 register rows — 7 × P1, 12 × P2, 8 × P3, 0 × P0** (P1-47…53, P2-51…62, P3-16…23). The pattern under twenty-two of the twenty-seven is unchanged: a control built at one door that a sibling door, a second caller, or the same walk does not carry. **P29 carries 26 of the 27** (P3-17 rides P27 wave 2). Total tracked: **192**.

### 5.23 P29a closure — the ingestion gate, the flywheel doors, the live record, the cut tool (2026-09-11, B131)

*The first of the two post-audit slices (B130). Twelve rows closed, each with a named test proven red first against the tree before its fix (the red table is B131 §3): P1-47, P1-48, P2-51, P2-52, P2-53 (§5.17); P1-49, P1-50, P2-54, P3-18 (§5.18); P2-61 (§5.21); P3-23 (§5.22); P3-16 (§5.17, the cut tool's fifth guard). Three register premises were corrected at planning and are recorded in B130 §2 (a ligature fold, not NFKC; the round's record inputs checkpointed, not "the rebuild's own cids"; revoke under the lane's lock, not a guard). **A1's ingestion line and its live-record acceptance line are honest again**: a client-named file leaves no name in the firm store, every persisted string is scanned, the three gap doors are one door, and the live record measures the readers under test and names the input that stales it. Suite at close: 1996. Version 0.9.1, tag `pilot-2.9`. Ids remain permanent labels; nothing here renumbers.*

**Stated limits (B131 §6):** the accept-side scan of a new-card body covers the structured classes only — a bare buyer name at accept time is the opening door's job (every door cleans it now); the gate-code fingerprint hashes three modules by structure, so any edit to them stales a recorded live measure by design (A1's run follows P29b); the cut refuses symlinks outright rather than scanning link text (the review-only mirror has no use for one).

### 5.24 P29b closure — crash safety, the purge closure, the write-back proofs (2026-09-11, B133)

*The second of the two post-audit slices (B130). Fourteen rows closed, each with a named test proven red first against the tree before its fix (the red table is B133 §3): P2-55, P2-56, P3-19 (§5.18); P1-51, P2-57, P2-58, P3-20, P3-21 (§5.19); P1-52, P2-59, P2-60, P3-22 (§5.20); P1-53 (§5.21); P2-62 (§5.22). The re-anchoring at `282f62c` found eighteen things B130's sketch had not (B132 §3), none a new row. **A1's restart-safety line and its purge guarantee are honest again — the P29 row is closed in full:** every appender carries one tail rule and every lane repairs and names its own tail; the kill switch never waits on a job; a derived artifact rebuilds after archiving its unreadable bytes aside and a draft never does; the replayed round record says what the round consumed; the purge follows lineage into the steward's queue and removes what no client could ever reach; both assistant doors withhold by the one predicate; an output no proof stood behind is never vouched for. Suite at close: 2037. Version 0.9.2, tag `pilot-2.10`. Ids remain permanent.*

**Stated limits (B133 §6):** the addenda lane has no lock (the loud `mkdir` collision guard stands after the max+1 mint); a corrupt links lane is named on its own board row and its guests see a 404; the lineage void reaches `proposed` proposals derived from purged cards — one derived from a held card stands with the card; orphan removal deletes un-attributable bytes on any purge without inspecting them; a facts file from before 0.9.2 reads `drifted` until re-confirmed; the steward's card route stays unwithheld by design.
