# The door index

*Audience: an operator — human or agent — driving this engine from outside. Every
entry point the engine exposes is on this page; if a door is not here, it does
not exist. Machine-compared against the live route table, the Makefile, and the
CLI's argparse tree by `tests/contracts/test_graph_doors.py`, in both
directions. When a test goes red: edit the code first, run `make check`, then
update the row the red test names — never the reverse. This document feeds the
pilot operator kit (P21). CI (`.github/workflows/check.yml`) is a caller of
`make check`, not a door of its own.*

## Web routes

The server binds 127.0.0.1 only (`python -m engine serve`). Reads are open;
every mutating door requires an operator (cookie session or SSO header). "confirm"
marks a two-step door; "job-lane" means the door 409s while a job runs for that
pursuit. FastAPI's own furniture — `/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc`, and the `/static` mount — is deliberately
outside this table, and the drift test pins that set closed.

The `surface` column (P27 wave 1, B110) says who reaches a door: `ui` —
the workbench shell; `guest` — the share page; `shell` — the page
itself; `api` — headless callers only (CLI, tests, the pilot host),
deliberately. `tests/contracts/test_ui_surfaces_doors.py` compares the
column against the path literals in the static sources in both
directions and pins the `api` set closed, so a door stays terminal only
on purpose. The pin is on paths, not methods.

### Session and health

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/session` | Declare an operator name AND role (mints the cookie); the role is what every event door records | open; 400 in SSO mode | ui |
| GET | `/api/session` | Who am I — name, role, and the declarable roles the sign-in picker offers | open | ui |
| GET | `/api/health` | Liveness: ok/mode/version/auth mode | open | api |

### Pursuits, uploads, orgs

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| GET | `/api/pursuits` | Board rows for every pursuit | open | ui |
| POST | `/api/pursuits` | Create a pursuit | operator | ui |
| GET | `/api/pursuits/{pursuit_id}` | One pursuit's detail | open | ui |
| GET | `/api/pursuits/{pursuit_id}/runs` | Run index for the pursuit | open | api |
| GET | `/api/pursuits/{pursuit_id}/runs/{run_id}` | Raw run-log records | open | api |
| PUT | `/api/pursuits/{pursuit_id}/inbox/{filename}` | Upload a document, optionally declaring its role (core/supplemental/target) | operator | ui |
| GET | `/api/orgs` | List org (tier-3 memory) records | open | api |
| POST | `/api/orgs` | Create an org | operator | api |
| POST | `/api/orgs/{org_id}/notes` | Write a firm observation — the org store's only writer | operator | api |

### Jobs (the pipeline runs here)

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/pursuits/{pursuit_id}/jobs` | Submit the `advance` job — runs the pipeline to the next gate | operator; 409 on conflict | ui |
| GET | `/api/jobs` | All jobs | open | api |
| GET | `/api/jobs/{job_id}` | One job's status | open | ui |
| POST | `/api/jobs/{job_id}/cancel` | Cooperative cancel | operator | api |

### Gates and waivers

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| GET | `/api/pursuits/{pursuit_id}/gate0` | Intake review: assumptions, gaps, red flags, cost forecast | open | ui |
| POST | `/api/pursuits/{pursuit_id}/gate0` | Decide gate 0 (corrections, answers, org link) | operator; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/gate1` | Strategy review: themes, forecast | open | ui |
| POST | `/api/pursuits/{pursuit_id}/gate1` | Decide gate 1 — approval freezes the brief | operator; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/gate2` | Plan review: coverage, sections, gaps, obligations | open | ui |
| POST | `/api/pursuits/{pursuit_id}/gate2` | Decide gate 2 — approval freezes the plan | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/waivers` | Waive a Tier-1 validation block (claim id + reason required) | operator; job-lane | ui |

### Gaps and pings

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/pursuits/{pursuit_id}/gaps` | Open a gap on the live plan/brief | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/gaps/{gap_id}/ping` | Route a gap to an SME | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/pings/{ping_id}/answer` | Answer a ping; optionally propose a KB card | operator; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/pings` | The pursuit's ping inbox | open | ui |
| GET | `/api/pings` | Cross-pursuit ping inbox | open | ui |

### Review, comments, revision

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| GET | `/api/pursuits/{pursuit_id}/review` | The internal review surface (annotated draft) | open | ui |
| POST | `/api/pursuits/{pursuit_id}/comments` | Internal comment/edit (lands pending) | operator; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/comments` | Pending + landed events | open | ui |
| DELETE | `/api/pursuits/{pursuit_id}/comments/{cid}` | Withdraw a pending item | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/comments/{cid}/include` | Promote a guest comment into the loop | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/comments/{cid}/dismiss` | Dismiss a pending comment | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/events` | Accept/reject an agent revision | operator | ui |
| POST | `/api/pursuits/{pursuit_id}/revise` | Submit one revision round as a job | operator; 409 on conflict | ui |
| GET | `/api/pursuits/{pursuit_id}/revisions` | Round records | open | api |
| GET | `/api/pursuits/{pursuit_id}/revisions/{n}` | One round + before/after diff | open | api |
| POST | `/api/pursuits/{pursuit_id}/accept` | Accept the pursuit — sections stamp final | operator; job-lane | ui |
| POST | `/api/pursuits/{pursuit_id}/outcome` | Record win/loss + buyer feedback | operator | ui |
| POST | `/api/pursuits/{pursuit_id}/effort` | Record review effort | operator | ui |

### Share links (guest review)

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/pursuits/{pursuit_id}/share` | Mint an expiring guest link | operator | ui |
| GET | `/api/pursuits/{pursuit_id}/share` | List links (carries secrets) | operator | ui |
| POST | `/api/pursuits/{pursuit_id}/share/{link_id}/revoke` | Kill a link | operator | ui |
| GET | `/share/{token}` | Guest review — the PAGE to a browser (`Accept: text/html`, the static shell, token unresolved), the JSON model otherwise; the page's own JSON fetch is the one access-logged view, and it carries the 404/410 a dead link earns | share-link scope; access-logged | guest |
| POST | `/share/{token}/comments` | Guest comment (lands pending, injection-screened) | share-link scope; access-logged | guest |

### Exports, downloads, write-back

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/pursuits/{pursuit_id}/export` | Render submission/review DOCX + recompose the bundle | operator; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/downloads` | The two headings — buyer list read from the submission bundle (a withheld firm-template fill lists as refused, its working copy under internal) | open | ui |
| GET | `/api/pursuits/{pursuit_id}/download/{name:path}` | Serve one file — closed allow-list from the bundle record | open; 403 outside the list; 409 naming what remains for a deliverable the bundle records as refused | ui |
| GET | `/api/pursuits/{pursuit_id}/writeback/preview` | Per-file facts preview for every declared lane | open (the preview half) | ui |
| POST | `/api/pursuits/{pursuit_id}/writeback/confirm` | Run every declared write-back lane; facts + bundle written | operator; confirm; job-lane | ui |
| GET | `/api/pursuits/{pursuit_id}/writeback/hand-fill` | The hand-completion record + what a human still owes (metadata record, pricing grid, case block, inline line) | open | ui |
| PUT | `/api/pursuits/{pursuit_id}/writeback/hand-fill` | Enter the values only a human supplies — server-stamped, last write wins per slot, empty clears | operator; job-lane | ui |

### Addenda

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/pursuits/{pursuit_id}/addenda` | Upload an amendment; deterministic impact scan | operator | api |
| GET | `/api/pursuits/{pursuit_id}/addenda` | List addenda | open | api |
| POST | `/api/pursuits/{pursuit_id}/addenda/{aid}/decide` | note_only or replan (archives the frozen plan) | operator; job-lane | api |

### KB and proposals

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| GET | `/api/kb/cards` | Card list with filters | open | ui |
| GET | `/api/kb/cards/{kb_id}` | Card detail + usage | open | api |
| GET | `/api/kb/proposals` | Proposal queue | open | ui |
| POST | `/api/kb/proposals` | Propose an edit or deprecation | operator | ui |
| POST | `/api/kb/proposals/{proposal_id}/decide` | Accept/reject a proposal | operator | ui |
| POST | `/api/kb/proposals/merge` | Batch-merge accepted proposals | operator | api |
| POST | `/api/kb/import.xlsx` | All-or-nothing workbook import → proposals | operator | api |
| GET | `/api/kb/export.xlsx` | Cards → workbook for SME review | operator | ui |

### Advisor and assistant

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| POST | `/api/advisor` | Ask the in-app product advisor (traced, zero-spend default) | operator | api |
| GET | `/api/advisor/cost` | Support-lane spend | open | api |
| GET | `/api/advisor/gaps` | Declined-topic worklist | open | api |
| POST | `/api/assistant/session` | Mint a steward-assistant session | operator | ui |
| GET | `/api/assistant/session/{session_id}` | Transcript + spend | operator | ui |
| POST | `/api/assistant/session/{session_id}/message` | One assistant turn | operator; 402 at ceiling | ui |
| GET | `/api/assistant/usage` | Lane usage report | operator | ui |

### Telemetry and shell

| method | path | purpose | gate | surface |
|---|---|---|---|---|
| GET | `/api/telemetry` | System-owner weekly view | open | ui |
| GET | `/api/telemetry/bench` | Bench view + last release record | open | ui |
| GET | `/` | The web shell (app.html) | open | shell |

## Make targets

| target | purpose |
|---|---|
| check | The offline suite — the phase gate; FakeCaller only, zero spend |
| slice | The M1 vertical slice end-to-end, headless, zero spend |
| eval | Eval harness + release gates; nonzero exit while a blocking bar is unmet |
| lock | Re-pin dependencies after an intentional change |
| gate-image | Build the extraction-gate container image |
| extraction-models | The one deliberately-online step: download weights, freeze the digest manifest |
| weights-verify | Verify `models/` against the COMMITTED manifest — a mismatch is a finding, never a refreeze |
| gate-tests | Container test leg without re-rendering the gate verdict |
| gate | The §A2 extraction gate: network-disabled container, verdict written to the milestone record |
| public-cut | Build + verify the public mirror in a staging dir — fresh single-commit history by default; with `PUBLIC_CUT_RELEASE=<published repo>` the verified tree is committed onto the existing public history instead (the update path, B89 §4a); the push stays a manual, owner-gated act in both modes. Two guards (B92, P25 item 7): every tracked path must be classified by exactly one manifest/deny entry, and release mode refuses any published file absent from the cut unless `tools/public_cut/deletions.txt` acknowledges it |

## CLI commands (`python -m engine …`)

| command | purpose |
|---|---|
| version | Print the engine version |
| check-run | Validate a run.jsonl: schemas, payload discipline, gapless seq |
| kb seed | Build the committed store from the fixture corpus |
| kb ingest | Ingest one firm-authored document |
| kb search | Card search with full retrieval trace |
| kb open | Open one card body |
| kb snapshot | Print the KB content snapshot id |
| kb purge | Purge a source client + cascade sweep |
| kb stats | Chunk-size distribution |
| kb where-used | Right of review for a name |
| kb provenance | Authorized read of restricted provenance |
| intake run | Document package + ramble → brief.json, offline |
| slice | The M1 vertical slice runner (`--ci` or `--live`) |
| serve | The web app on 127.0.0.1 (host is deliberately not an argument) |
| eval | The eval harness + release gates |

## Module `__main__` doors

| module | purpose |
|---|---|
| engine | The CLI dispatcher above |
| engine.extraction.weights | `freeze` / `verify` the weights digest manifest |
| engine.extraction.gate | Render the §A2 gate verdict into the milestone record |
| engine.extraction.worker | Internal — sandbox subprocess, spawned by the engine, not an operator door |
| engine.extraction._child | Internal — sandbox subprocess, spawned by the engine, not an operator door |
| tools.public_cut | The public-cut builder — normally driven via `make public-cut` (B87) |

## Regeneration doors (`python -c`)

Deliberate one-liners that re-record a pinned artifact after an intentional
change to its source. The drift test proves each named door still resolves
(one direction; a NEW regeneration function is added here deliberately, by
hand — B87 §2).

| door | regenerates |
|---|---|
| `from engine.evals.voice import write_recorded` | `evals/voice/recorded.json`, after a deliberate `config/voice-spec.md` change |
| `from engine.intake.evalset import write_recorded` | `evals/injection/recorded.json`, after a deliberate injection-evalset change |
