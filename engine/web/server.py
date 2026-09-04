"""The web shell app factory (B37/D1): FastAPI, JSON API, polling —
127.0.0.1 only, one server per workspace (serve.lock, flock-held so a
dead process releases it), neutral branding (D31).

Zero spend by default (CLAUDE.md rule 2): the default caller factory is
FakeCaller over the product-side derive-from-prompt script, mode
"dry_run". A live web flavor does not exist at c8 — wiring one requires
the same named-refusal ceremony the slice --live path carries, and it
arrives only when a milestone needs it.

The `at` boundary (D13): every mutating route takes an optional `at`;
when absent the server computes now() EXACTLY ONCE per request at this
boundary — no wall clock below it, tests always inject.
"""

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from engine.cli.slice import KB_ROOT, _extras  # the shared digest extras
from engine.web.fake_script import revision_script
from engine.intake.brief import IntakeDoc, IntakePackage
from engine.llm import FakeCaller, TracedCaller
from engine.pipeline import advance
from engine.runlog import read_run, read_run_report
from engine.version import engine_version
from engine.web import state as state_models
from engine.web.auth import DECLARABLE_ROLES, AuthSeam
from engine.contracts import ContractError, write_bytes_atomic, write_json_atomic
from engine.web.events import EventsError, EventsLane
from engine.web import limits
from engine.web.payload import field
from engine.web.headers import SecurityHeadersMiddleware
from engine.web.jobs import JobConflict, JobNotFound, JobRunner
from engine.workspace import PursuitDir, orgs as org_registry
from engine.workspace.lock import WorkspaceLocked, workspace_lock

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The one pursuit-id shape (v1 P9-B3 lesson: ONE copy of the regex).
PURSUIT_ID = re.compile(r"^pur_[a-z0-9][a-z0-9_-]{0,40}$")
RESERVED_IDS = {"pur_support"}  # D21: the advisor's lane must stay unmixable


def _default_make_caller(log):
    # revision_script = ci_script + the revision arm: the serve default
    # must cover EVERY dry_run lane, or the clickable review loop dies
    # on an unscripted agent (caught seeding the look-and-feel demo)
    return TracedCaller(FakeCaller(revision_script()), log)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def create_app(workspace: Path, *, make_caller=_default_make_caller,
               mode: str = "dry_run", auth_config: Path | None = None,
               now=_now_utc,
               allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS) -> FastAPI:
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    # serve.lock: flock-held for app life — a second server on this
    # workspace refuses, a dead one releases (v1 keeper design). Since
    # P25 item 2 the SAME lock is taken by every mutating CLI command
    # (engine.workspace.lock), so a CLI cannot race a live server.
    try:
        lock = workspace_lock(workspace, holder="server")
    except WorkspaceLocked as exc:
        raise RuntimeError(f"{exc}; one server per workspace") from exc

    @asynccontextmanager
    async def lifespan(app):
        yield
        lock.release()

    app = FastAPI(title="RFP Engine", lifespan=lifespan)
    # P25 item 4 (P0-7): the Host header must be one the operator serves
    # (DNS rebinding closes here; A5's proxy adds its host through the
    # parameter), and every response carries the baseline headers — the
    # headers middleware is outermost so even a host refusal carries them.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts),
                       www_redirect=False)
    app.add_middleware(SecurityHeadersMiddleware)
    seam = AuthSeam(auth_config)
    runner = JobRunner(workspace)
    # A workspace carrying its own kb/ owns its store (the fixture-chain
    # layout); the committed store is the product default.
    kb_root = workspace / "kb" if (workspace / "kb").is_dir() else KB_ROOT

    def extras(stage: str) -> dict:
        return _extras(stage, kb_root=kb_root)
    app.state.workspace = workspace
    app.state.runner = runner
    app.state.auth = seam

    def operator(request: Request) -> str:
        return seam.operator(request)

    def actor_role(request: Request) -> str:
        # P27 wave 1 (M-9): the role a door records is the SESSION's —
        # never a payload field, never a hardcoded default
        return seam.role(request)

    app.state.clock = now  # the injectable clock (tests move it here)

    def now() -> str:  # noqa: F811 — shadows the parameter on purpose
        return app.state.clock()

    def _at(payload: dict | None) -> str:
        """P26a Group D (P0-11): the SERVER stamps every mutating door's
        clock. A client `at` in a mutating payload is refused, not
        silently ignored — the door is visibly closed (the browser never
        sent one; tests inject through create_app(now=)). Read-time
        staleness inputs use _read_at, never this.

        P27 wave 1 (M-9): the same boundary refuses a client `actor_role`
        — the session names the role (Depends(actor_role)); every door
        that records one calls _at first."""
        if payload and payload.get("at") is not None:
            raise HTTPException(
                422, "the server stamps the clock — a client-supplied 'at' "
                     "is refused on every mutating door (P0-11)")
        if payload and payload.get("actor_role") is not None:
            raise HTTPException(
                422, "the session names the role — a client-supplied "
                     "'actor_role' is refused on every door (P27, M-9)")
        return now()

    def _read_at(at: str | None) -> str:
        """A read-time staleness probe (KB card staleness) — the one place
        a caller may name a moment, because nothing is recorded."""
        return at or now()

    def _pursuit_root(pursuit_id: str) -> Path:
        # P25 item 4 (P2-17): the id shape is checked at every door, not
        # only at creation — `..` used to pass is_dir() and PursuitDir's
        # mkdirs then landed eleven directories in the workspace's parent
        if not PURSUIT_ID.match(pursuit_id or ""):
            raise HTTPException(422, f"pursuit id {pursuit_id!r} is not a "
                                     "pursuit id")
        root = workspace / pursuit_id
        # existence check BEFORE PursuitDir — its __init__ mkdirs, and a
        # GET must never create a phantom pursuit (v1 trap 1).
        if not root.is_dir():
            raise HTTPException(404, f"no pursuit {pursuit_id!r}")
        return root

    # -- session / health --------------------------------------------------

    @app.post("/api/session")
    def establish_session(payload: dict, response: Response):
        token = seam.establish(field(payload, "name", "str", default=""),
                               field(payload, "role", "str", default=""))
        response.set_cookie("operator", token, httponly=True,
                            samesite="lax")
        session = seam._sessions[token]
        return {"operator": session["name"], "role": session["role"],
                "roles": list(DECLARABLE_ROLES)}

    @app.get("/api/session")
    def whoami(request: Request):
        # the declarable list rides along: the shell's role picker reads
        # it from here, so the enum has one copy (P27, M-9)
        return {**seam.whoami(request), "roles": list(DECLARABLE_ROLES)}

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": mode, "version": engine_version(),
                "auth_mode": seam.mode}

    # -- board / detail / runs (reads: open) -------------------------------

    @app.get("/api/pursuits")
    def board():
        return state_models.board(workspace)

    @app.get("/api/pursuits/{pursuit_id}")
    def detail(pursuit_id: str):
        out = state_models.detail(workspace, pursuit_id)
        if out is None:
            raise HTTPException(404, f"no pursuit {pursuit_id!r}")
        return out

    @app.get("/api/pursuits/{pursuit_id}/runs")
    def runs(pursuit_id: str):
        root = _pursuit_root(pursuit_id)
        out = []
        runs_dir = root / "runs"
        busy = runner.busy(pursuit_id) is not None
        for run_file in sorted(runs_dir.glob("*/run.jsonl"),
                               key=lambda p: int(p.parent.name[4:])
                               if p.parent.name[4:].isdigit() else -1) \
                if runs_dir.exists() else []:
            records, torn = read_run_report(run_file)
            header = records[0]["run"] if records else {}
            footer = records[-1]["run"] if records and \
                records[-1].get("record_type") == "run_end" else None
            row = {"run_id": run_file.parent.name,
                   "mode": header.get("mode"),
                   "records": len(records),
                   # P2-20: footerless = in_flight only while a job holds
                   # this pursuit; otherwise the run is honestly UNCLOSED
                   # (the job lane and rehydrate close crashed runs, so
                   # this names a hard kill the runbook owns)
                   "status": (footer or {}).get(
                       "status", "in_flight" if busy else "unclosed"),
                   "totals": (footer or {}).get("totals")}
            if torn:
                row["torn_tail"] = torn  # P1-17: reported, never hidden
            out.append(row)
        return out

    @app.get("/api/pursuits/{pursuit_id}/runs/{run_id}")
    def run_records(pursuit_id: str, run_id: str):
        root = _pursuit_root(pursuit_id)
        run_file = root / "runs" / Path(run_id).name / "run.jsonl"
        if not run_file.exists():
            raise HTTPException(404, f"no run {run_id!r}")
        # digest-clean by construction: the run log never carries raw
        # client text (O7), so serving it verbatim is safe.
        return read_run(run_file)

    # -- pursuit creation + uploads (mutating) -----------------------------

    @app.post("/api/pursuits")
    def create_pursuit(payload: dict, who: str = Depends(operator)):
        _at(payload)  # P0-11: a client clock is refused here too
        pursuit_id = field(payload, "pursuit_id", "str", default="")
        if not PURSUIT_ID.match(pursuit_id):
            raise HTTPException(
                422, "pursuit_id must match pur_[a-z0-9][a-z0-9_-]{1,40}")
        if pursuit_id in RESERVED_IDS:
            raise HTTPException(
                409, f"{pursuit_id!r} is reserved — the advisor's support "
                     "lane must stay structurally unmixable (D21)")
        if (workspace / pursuit_id).exists():
            raise HTTPException(409, f"{pursuit_id!r} already exists")
        PursuitDir(workspace, pursuit_id)
        return {"pursuit_id": pursuit_id, "created_by": who}

    # -- org registry (P17/C6, B75§2: tier-3 memory's identity + writer) --

    @app.get("/api/orgs")
    def orgs_list():
        return {"orgs": org_registry.list_orgs(workspace)}

    @app.post("/api/orgs")
    def orgs_create(payload: dict, who: str = Depends(operator)):
        from engine.contracts import ContractError
        try:
            return org_registry.create_org(
                workspace, payload.get("name", ""), created_by=who,
                at=_at(payload))
        except ContractError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/orgs/{org_id}/notes")
    def orgs_note(org_id: str, payload: dict, who: str = Depends(operator)):
        """The org store's only writer, over HTTP: a typed firm-authored
        observation — the door stamps human_authored; buyer text has no
        path in (B69§3)."""
        from engine.contracts import ContractError
        try:
            kb_id = org_registry.write_org_note(
                workspace, org_id, operator=who, at=_at(payload),
                title=payload.get("title", ""), body=payload.get("body", ""))
        except ContractError as exc:
            raise HTTPException(409, str(exc))
        return {"kb_id": kb_id, "org_id": org_id, "by": who}

    @app.put("/api/pursuits/{pursuit_id}/inbox/{filename}")
    async def upload(pursuit_id: str, filename: str, request: Request,
                     role: str | None = None,
                     who: str = Depends(operator)):
        root = _pursuit_root(pursuit_id)
        clean = Path(filename).name  # traversal defense
        if not clean or clean != filename:
            raise HTTPException(422, "plain filenames only")
        if role is not None and role not in ("core", "supplemental",
                                             "target"):
            raise HTTPException(
                422, "role must be core, supplemental, or target (B67 §3: "
                     "the role is declared, never inferred)")
        body = await limits.read_body_capped(
            request, limits.MAX_INBOX_UPLOAD_BYTES)  # P0-8: capped, streamed
        if not body:
            raise HTTPException(400, "empty upload")
        with _mutate(pursuit_id):  # P1-22: the inbox write + roles RMW
            target = root / "inbox" / clean
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(target, body)  # P0-6
            if role is not None:
                roles_path = root / "inbox" / "roles.json"
                roles = (json.loads(roles_path.read_text(encoding="utf-8"))
                         if roles_path.exists() else {})
                roles[clean] = role
                write_json_atomic(roles_path, roles)  # P0-6: a record
        out = {"stored": f"inbox/{clean}", "bytes": len(body), "by": who}
        if role is not None:
            out["role"] = role
        return out

    # -- jobs --------------------------------------------------------------

    def _resolve_targets(root) -> dict:
        """THE one declared-target resolver (P16/C5): every consumer of
        "which file(s) is the response vehicle" — the advance job, the
        gate-collapse job, the cost forecast — goes through here, so a
        declared DOCX target can never fall to glob order in one site
        while another honors it. Declared roles are authoritative
        (targets in filename order, ANY parseable type — parse_target
        owns the loud refusal for unsupported ones); a missing declared
        file refuses; an undeclared inbox keeps the legacy
        first-workbook behavior byte-for-byte."""
        from engine.contracts import ContractError
        inbox = root / "inbox"
        roles_path = inbox / "roles.json"
        roles = (json.loads(roles_path.read_text(encoding="utf-8"))
                 if roles_path.exists() else {})
        if roles:
            targets = [inbox / n for n in sorted(roles)
                       if roles[n] == "target"]
            missing = [t.name for t in targets if not t.is_file()]
            if missing:
                raise ContractError(
                    "declared target(s) missing from inbox/: "
                    + ", ".join(missing))
            core = next((inbox / n for n in sorted(roles)
                         if roles[n] == "core"), None)
            return {"targets": targets, "core": core, "declared": True}
        workbooks = sorted(inbox.glob("*.xlsx"))
        return {"targets": workbooks[:1], "core": None, "declared": False}

    def _advance_target(pursuit_id: str, at: str):
        def target(job: dict):
            pursuit = PursuitDir(workspace, pursuit_id)
            inbox = pursuit.root / "inbox"
            workbooks = sorted(inbox.glob("*.xlsx"))
            ramble = inbox / "ramble.md"
            pack = inbox / "research-pack.md"
            roles_path = inbox / "roles.json"
            roles = (json.loads(roles_path.read_text(encoding="utf-8"))
                     if roles_path.exists() else {})
            resolved = _resolve_targets(pursuit.root)

            def intake_package(_p):
                from engine.contracts import ContractError
                if roles:
                    docs = []
                    for path in sorted(inbox.iterdir()):
                        if path.suffix.lower() not in (".pdf", ".docx",
                                                       ".xlsx"):
                            continue
                        role = roles.get(path.name)
                        docs.append(IntakeDoc(
                            path=path,
                            kind=("rfp_main" if role == "core" else "other"),
                            role=role))
                    if not docs:
                        raise ContractError(
                            "roles.json names no readable documents — "
                            "upload the RFP package first")
                    if not any(d.role == "core" for d in docs):
                        raise ContractError(
                            "no document declared role=core — the one you "
                            "would read if you read only one (B67 §3)")
                    return IntakePackage(
                        pursuit_id=pursuit_id, docs=docs,
                        ramble=(ramble.read_text(encoding="utf-8")
                                if ramble.exists() else ""))
                if not workbooks:
                    raise ContractError(
                        "no .xlsx in inbox/ — upload the RFP package first")
                return IntakePackage(
                    pursuit_id=pursuit_id,
                    docs=[IntakeDoc(path=workbooks[0], kind="rfp_main")],
                    ramble=(ramble.read_text(encoding="utf-8")
                            if ramble.exists() else ""))

            adv = advance(
                pursuit, make_caller=make_caller, mode=mode,
                kb_root=kb_root, at=at, extras=extras,
                intake_package=intake_package,
                research_pack=pack if pack.exists() else None,
                targets=(resolved["targets"] if resolved["declared"]
                         else None),
                core_doc=resolved["core"],
                workbook=(None if resolved["declared"]
                          else next(iter(resolved["targets"]), None)),
                decide_gate1=None, decide_gate2=None,  # gates are humans'
                actor=job["by"])
            if adv.status in ("ok",):
                return "done", ("advance complete: "
                                + ", ".join(adv.ran_stages or ["nothing new"]))
            if adv.status in ("awaiting_gate", "awaiting_gap"):
                return "done", (f"{adv.status} at {adv.stopped_at}"
                                + (": " + "; ".join(adv.problems)
                                   if adv.problems else ""))
            return ("refused" if adv.status == "refused" else "error",
                    "; ".join(adv.problems) or adv.status)
        return target

    @app.post("/api/pursuits/{pursuit_id}/jobs")
    def submit_job(pursuit_id: str, payload: dict,
                   who: str = Depends(operator)):
        _pursuit_root(pursuit_id)
        kind = payload.get("kind")
        if kind != "advance":
            raise HTTPException(422, f"unknown job kind {kind!r} — c8 "
                                     "ships advance; revise/export arrive "
                                     "with their lanes")
        at = _at(payload)
        try:
            job = app.state.runner.submit(
                kind=kind, pursuit_id=pursuit_id, by=who, at=at,
                target=_advance_target(pursuit_id, at))
        except JobConflict as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse(job, status_code=202)

    @app.get("/api/jobs")
    def jobs():
        return app.state.runner.jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        out = app.state.runner.job(job_id)
        if out is None:
            raise HTTPException(404, f"unknown job {job_id!r}")
        return out

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, who: str = Depends(operator)):
        try:
            return app.state.runner.cancel(job_id, who)
        except JobNotFound as exc:
            raise HTTPException(404, str(exc))
        except JobConflict as exc:
            raise HTTPException(409, str(exc))

    # -- the advisor (D21; c18) --------------------------------------------

    from engine.llm.caller import cost_usd as _cost_usd
    from engine.support import (
        AdvisorError,
        SupportTrace,
        build_user_prompt,
        parse_reply,
        pursuit_digest,
        system_prompt,
    )

    support = SupportTrace(workspace)
    advisor_fake = FakeCaller({})  # zero-spend default; tests inject

    def _advisor_call(prompt: str, system: str):
        caller = app.state.advisor_caller or advisor_fake
        return caller.call_for("advisor", tier="fast", prompt=prompt,
                               system=system)

    app.state.advisor_caller = None
    app.state.support = support

    @app.post("/api/advisor")
    def advisor(payload: dict, who: str = Depends(operator)):
        question = str(payload.get("question", "")).strip()
        at = _at(payload)
        if not 3 <= len(question) <= 2000:
            raise HTTPException(422, "question must be 3-2000 characters")
        digest = ""
        pursuit_id = payload.get("pursuit_id")
        if pursuit_id:
            try:
                # facts only, existence-checked FIRST — asking about a
                # pursuit must never create one
                digest = pursuit_digest(workspace, pursuit_id)
            except FileNotFoundError:
                raise HTTPException(404, f"no pursuit {pursuit_id!r}")
        history = field(payload, "history", "list", default=[])
        result = _advisor_call(
            build_user_prompt(question, digest=digest, history=history),
            system_prompt())
        cost = _cost_usd("fast", result, None)
        try:
            reply = parse_reply(result.text)
        except AdvisorError as exc:
            support.record(at=at, by=who, outcome="error",
                           question=question, model=result.model,
                           input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens,
                           cost_usd=cost, detail=str(exc))
            raise HTTPException(502, f"advisor wire refused: {exc}")
        if reply["kind"] == "not_covered":
            support.record(at=at, by=who, outcome="declined",
                           question=question, model=result.model,
                           input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens,
                           cost_usd=cost,
                           detail=f"by {who}; topic: {reply['topic']}")
        else:
            support.record(at=at, by=who, outcome="ok", question=question,
                           model=result.model,
                           input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens,
                           cost_usd=cost)
        return reply

    @app.get("/api/advisor/cost")
    def advisor_cost():
        return support.cost() or {"note": "no support calls yet"}

    @app.get("/api/advisor/gaps")
    def advisor_gaps():
        return support.gaps()

    # -- KB export (D22, Q2: export-only at P9) ----------------------------

    # -- telemetry (D23; c21) ----------------------------------------------
    # Derive-never-store: computed from the records at request time, so a
    # figure on the screen cannot disagree with the record it summarises.
    # The screen and the release gate resolve through the SAME metric
    # objects — v1's eval numbers never reached its UI, and a dashboard
    # computing its own version of a gated number is how the two drift.

    @app.get("/api/telemetry")
    def telemetry():
        from engine.metrics.resolver import Corpus
        from engine.metrics.views import render_view
        return render_view("system_owner_weekly", Corpus(workspace))

    @app.get("/api/telemetry/bench")
    def telemetry_bench():
        """Bench results get their OWN view (REPORTING_SPEC): visible,
        never mixed into a production series. Reads the last written
        release record rather than re-running the suite — `make eval`
        owns that, and a dashboard that could trigger a long eval run is
        a dashboard that can hang."""
        from engine.evals.release import RELEASES_DIR
        from engine.metrics.resolver import Corpus
        from engine.metrics.views import render_view
        from engine.version import engine_version

        payload = render_view("bench", Corpus(workspace))
        record_dir = RELEASES_DIR / engine_version()
        record_path = record_dir / "eval-results.json"
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            payload["release"] = {
                "engine_version": record["engine_version"],
                "generated_at": record["generated_at"],
                "eval_pass_state": record["eval_pass_state"],
                "blocking_failures": record["blocking_failures"],
                "suites": {name: {"status": entry["status"],
                                  "basis": entry["basis"]}
                           for name, entry in record["suites"].items()},
                "gates": record["gates"],
            }
        else:
            payload["release"] = None
            payload["release_absent_reason"] = (
                f"no release record for {engine_version()} — run `make eval`")
        return payload

    # -- KB curation (D20; c20) --------------------------------------------
    # v1 shipped import-to-draft with a terminal-only approve command, so
    # imported content sat published, valid and invisible to every draft.
    # Mint and approve ship on the same surface here.

    def _kb_store():
        from engine.kb import KBStore
        return KBStore(kb_root)

    def _workspace_records() -> list[dict]:
        from engine.metrics.walker import walk
        return [r for p in walk(workspace) for r in p.runs]

    @app.get("/api/kb/cards")
    def kb_cards(q: str = "", layer: str = "", staleness: str = "",
                 sort: str = "kb_id", at: str | None = None):
        from engine.kb.curation import cards_view
        return {"cards": cards_view(_kb_store(), q=q, layer=layer,
                                    staleness_filter=staleness, sort=sort,
                                    at=_read_at(at))}

    @app.get("/api/kb/cards/{kb_id}")
    def kb_card(kb_id: str, at: str | None = None):
        from engine.kb.curation import card_detail
        store = _kb_store()
        if not store.card_exists(kb_id):
            raise HTTPException(status_code=404, detail=f"no card {kb_id}")
        return card_detail(store, kb_id, records=_workspace_records(),
                           at=_read_at(at))

    @app.get("/api/kb/proposals")
    def kb_proposals(status: str | None = None):
        from engine.flywheel.proposals import ProposalStore
        try:
            return {"proposals": ProposalStore(kb_root).list(status=status)}
        except ContractError as exc:
            # M-30: one bad file names itself instead of 500ing the inbox.
            raise HTTPException(status_code=409, detail=str(exc))

    def _kb_id_shape(value) -> str:
        """P2-23 (P26b-1, B112): the store refuses a malformed id before it
        can name a path; the door turns that into a 422 naming the shape."""
        from engine.kb.identity import IdShapeError, require_kb_id
        try:
            return require_kb_id(value)
        except IdShapeError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    def _proposal_id_shape(value) -> str:
        from engine.flywheel.proposals import IdShapeError, require_proposal_id
        try:
            return require_proposal_id(value)
        except IdShapeError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/api/kb/proposals")
    def kb_propose(payload: dict, who: str = Depends(operator)):
        from engine.kb.curation import (CurationRefused, propose_deprecation,
                                        propose_edit)
        store = _kb_store()
        kb_id = _kb_id_shape(field(payload, "kb_id", "str", default=""))
        if not store.card_exists(kb_id):
            raise HTTPException(status_code=404, detail=f"no card {kb_id}")
        at = _at(payload)
        try:
            if payload.get("action") == "deprecate":
                return propose_deprecation(
                    store, kb_id, operator=who, at=at,
                    records=_workspace_records(),
                    note=payload.get("note", ""))
            return propose_edit(store, kb_id,
                                field(payload, "changes", "dict", default={}),
                                operator=who, at=at,
                                note=payload.get("note", ""))
        except CurationRefused as refusal:
            raise HTTPException(status_code=409, detail=str(refusal))

    @app.post("/api/kb/proposals/{proposal_id}/decide")
    def kb_decide(proposal_id: str, payload: dict,
                  who: str = Depends(operator)):
        from engine.flywheel.proposals import ProposalStateError, ProposalStore
        proposal_id = _proposal_id_shape(proposal_id)  # P2-23
        decision = payload.get("decision")
        if decision not in ("accepted", "rejected"):
            raise HTTPException(status_code=400,
                                detail="decision must be accepted or rejected")
        if decision == "accepted":
            # Accepting is a merge: it goes through the batch door so the
            # curation log records it exactly like any other merge.
            return kb_merge({"proposal_ids": [proposal_id],
                             "at": payload.get("at")}, who)
        try:
            return ProposalStore(kb_root).decide(
                proposal_id, decision="rejected", by=who, at=_at(payload),
                note=payload.get("note", ""))
        except ProposalStateError as refusal:  # P1-39: decided once
            raise HTTPException(status_code=409, detail=str(refusal))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="no such proposal")

    @app.post("/api/kb/proposals/merge")
    def kb_merge(payload: dict, who: str = Depends(operator)):
        from engine.kb.curation import CurationRefused, merge_batch
        ids = field(payload, "proposal_ids", "list", default=[])
        if not ids:
            raise HTTPException(status_code=400,
                                detail="no proposal_ids given")
        ids = [_proposal_id_shape(pid) for pid in ids]  # P2-23: each element
        try:
            return merge_batch(_kb_store(), ids, operator=who,
                               at=_at(payload))
        except CurationRefused as refusal:
            raise HTTPException(status_code=409, detail=str(refusal))
        except ContractError as exc:  # M-30: a bad proposal file, by name
            raise HTTPException(status_code=409, detail=str(exc))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="no such proposal")

    @app.post("/api/kb/import.xlsx")
    async def kb_import(request: Request, who: str = Depends(operator)):
        """All-or-nothing: one bad cell and no proposal is opened."""
        import tempfile

        from engine.kb.xlsx import WorkbookError, submit_import
        body = await limits.read_body_capped(
            request, limits.MAX_XLSX_IMPORT_BYTES)  # P0-8
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / "upload.xlsx"
            path.write_bytes(body)
            try:
                return submit_import(_kb_store(), path, operator=who,
                                     at=_at(None))
            except WorkbookError as refusal:
                raise HTTPException(status_code=400, detail=str(refusal))

    @app.get("/api/kb/export.xlsx")
    def kb_export(who: str = Depends(operator)):
        """Cards -> a clean workbook for SME review in Excel. Delegates to
        engine/kb/xlsx.py so export and import share ONE column
        definition and cannot disagree about what a column means.
        Restricted provenance never appears — card fronts carry none by
        design, and the export adds none."""
        import tempfile

        from engine.kb import KBStore
        from engine.kb.xlsx import export_cards
        store = KBStore(kb_root)
        with tempfile.TemporaryDirectory() as workdir:
            path = export_cards(store, Path(workdir) / "kb-cards.xlsx")
            payload = path.read_bytes()
        return Response(
            payload,
            media_type="application/vnd.openxmlformats-officedocument"
                       ".spreadsheetml.sheet",
            headers={"Content-Disposition":
                     'attachment; filename="kb-cards.xlsx"'})

    # -- the addendum lane (D18; c17) --------------------------------------

    from engine.web.addenda import AddendumError, AddendumLane

    def _addendum_lane(pursuit_id: str) -> AddendumLane:
        _pursuit_root(pursuit_id)
        return AddendumLane(PursuitDir(workspace, pursuit_id))

    @app.post("/api/pursuits/{pursuit_id}/addenda")
    async def upload_addendum(pursuit_id: str, request: Request,
                              filename: str = "addendum.md",
                              who: str = Depends(operator)):
        lane = _addendum_lane(pursuit_id)
        body = await limits.read_body_capped(
            request, limits.MAX_ADDENDUM_BYTES)  # P0-8
        pursuit = PursuitDir(workspace, pursuit_id)
        slots_by_id = None
        slots_path = pursuit.root / "slots.json"
        if slots_path.exists():
            container = json.loads(slots_path.read_text(encoding="utf-8"))
            slots_by_id = {s["slot_id"]: s for s in container["slots"]}
        if not (pursuit.root / "plan.json").exists():
            raise HTTPException(400, "no plan yet — an addendum's impact "
                                     "scan reads the pursuit plan")
        try:
            return lane.store(filename=Path(filename).name, body=body,
                              at=_at(None), actor=who,
                              slots_by_id=slots_by_id)
        except AddendumError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/pursuits/{pursuit_id}/addenda")
    def list_addenda(pursuit_id: str):
        return _addendum_lane(pursuit_id).list()

    @app.post("/api/pursuits/{pursuit_id}/addenda/{aid}/decide")
    def decide_addendum(pursuit_id: str, aid: str, payload: dict,
                        who: str = Depends(operator)):
        lane = _addendum_lane(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "planning")
            try:
                meta = lane.decide(log, aid=aid,
                                   decision=payload.get("decision", ""),
                                   note=payload.get("note", ""),
                                   at=at, actor=who)
            except AddendumError as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
        return meta

    # -- export + downloads (D20; c16; bundle P18/C6) ----------------------

    from engine.assembly.bundle import compose_bundle, declared_deliverables
    from engine.assembly.bindings import assert_current
    from engine.assembly.docx import render_review, render_submission

    @app.post("/api/pursuits/{pursuit_id}/export")
    def export(pursuit_id: str, payload: dict,
               who: str = Depends(operator)):
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        lane = payload.get("lane", "both")
        at = _at(payload)
        out: dict = {}
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "export")
            try:
                # P25 item 8: the bindings verify ONCE at the door (P0-2,
                # P0-16); the submission lane also carries the block and
                # the owed pends (P0-20)
                assert_current(pursuit, lane=(
                    "submission" if lane in ("both", "submission")
                    else "review"))
                if lane in ("both", "submission"):
                    out["submission"] = render_submission(pursuit, log,
                                                          at=at)
                if lane in ("both", "review"):
                    out["review"] = render_review(pursuit, log, at=at)
                # every exit door recomposes the bundle (P18/C6): the
                # render just changed the to-the-buyer set's state
                out["bundle"] = compose_bundle(pursuit, log, at=at,
                                               composed_by=who)
            except (ContractError, FileNotFoundError, ValueError) as exc:
                # ValueError: python-docx refuses XML-incompatible text
                # (P2-29a) — a typed 409 with the run closed, never a 500
                # over a footerless run
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
        return out

    def _bundle_record(root: Path) -> dict | None:
        bundle_path = root / "exports" / "submission-bundle.json"
        if not bundle_path.is_file():
            return None  # never composed — nothing is shippable yet
        return json.loads(bundle_path.read_text(encoding="utf-8"))

    @app.get("/api/pursuits/{pursuit_id}/downloads")
    def downloads(pursuit_id: str):
        """The two literal headings (v1 keeper) — and the buyer half now
        reads the BUNDLE, never the directory (P18/C7, B77§2 D6): a
        file no record vouches for is not shippable, however it got
        into the folder. Filled buyer forms are buyer deliverables
        (B77§1a), so they list here, not under Internal."""
        root = _pursuit_root(pursuit_id)
        bundle = _bundle_record(root)
        deliverables = bundle["deliverables"] if bundle else []
        buyer = sorted(d["name"] for d in deliverables
                       if d["status"] == "produced")
        rev = root / "exports" / "review"
        return {
            "to_the_buyer": buyer,
            "internal_do_not_send": sorted(
                p.name for p in rev.iterdir()) if rev.exists() else [],
            # P27 wave 1: a withheld deliverable and its reason render on
            # the finish panel without a 409 round-trip — the record's
            # own words, the same ones the download door refuses with
            "refused": sorted(
                ({"name": d["name"], "reason": d.get("reason", "refused")}
                 for d in deliverables if d["status"] == "refused"),
                key=lambda d: d["name"]),
        }

    @app.get("/api/pursuits/{pursuit_id}/download/{name:path}")
    def download(pursuit_id: str, name: str):
        root = _pursuit_root(pursuit_id)
        clean = Path(name).name  # traversal defense
        bundle = _bundle_record(root)
        if bundle:
            for entry in bundle["deliverables"]:
                if entry["name"] == clean and entry["status"] == "refused":
                    # P26a item 1 (P1-27): a withheld buyer copy names
                    # what remains — never a bare 404 over a real record
                    raise HTTPException(409, entry.get("reason", "refused"))
                if entry["name"] == clean and entry["status"] == "produced":
                    path = root / entry["path"]  # served by the RECORD's
                    if not path.resolve().is_relative_to(root.resolve()):
                        raise HTTPException(403, "the bundle record names a "
                                                 "path outside the pursuit")
                    if path.is_file():           # path, never a name scan
                        return FileResponse(path, filename=clean)
        review = root / "exports" / "review" / clean
        if review.is_file():
            return FileResponse(review, filename=clean)
        # a closed allow-list, never a general file server: anything the
        # bundle does not vouch for and the review lane does not hold is
        # refused even if it exists somewhere on disk
        if (root / clean).exists() or (root / name).exists():
            raise HTTPException(
                403, f"{name!r} is not a download — only the exports "
                     "lanes serve files")
        raise HTTPException(404, f"no export named {name!r}")

    # -- write-back (D19; c15; docx lane P16/C8) ---------------------------

    from engine.assembly.docx_writeback import (
        preview_docx_writeback,
        run_docx_writeback,
    )
    from engine.assembly.template_fill import (
        preview_template_fill,
        run_template_fill,
    )
    from engine.assembly.writeback import preview_writeback, run_writeback

    def _writeback_bindings(pursuit) -> list[dict]:
        """The deliverable set, derived by the ENGINE from the container
        (P18/C6): declared_deliverables replaces the one-string
        dispatcher (P17/C10) — a mixed target set gets EVERY lane it
        declares, not the first suffix match, and the identity is still
        the container's own (source_mode + sources[] digests), never
        inbox state."""
        frozen_plan = pursuit.read_frozen("pursuit_plan")
        container = pursuit.read_artifact(
            frozen_plan.get("slots_ref", "slots.json"))
        return declared_deliverables(pursuit, container)

    def _preview_one(pursuit, binding, at: str) -> dict:
        if binding["lane"] == "template_fill":
            return preview_template_fill(pursuit, at=at)
        if binding["lane"] == "docx_writeback":
            return preview_docx_writeback(pursuit, at=at, binding=binding)
        return preview_writeback(pursuit, at=at, binding=binding)

    def _run_one(pursuit, log, binding, at: str, who: str) -> dict:
        if binding["lane"] == "template_fill":
            return run_template_fill(pursuit, log, at=at, confirmed_by=who)
        if binding["lane"] == "docx_writeback":
            return run_docx_writeback(pursuit, log, at=at,
                                      confirmed_by=who, binding=binding)
        return run_writeback(pursuit, log, at=at, confirmed_by=who,
                             binding=binding)

    @app.get("/api/pursuits/{pursuit_id}/writeback/preview")
    def writeback_preview(pursuit_id: str, at: str | None = None):
        """One uniform shape for every pursuit (B77§2 D4): {"files":
        [per-file facts...], "refused": [{lane, file, reason}...]} —
        409 only when NOTHING previews."""
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        try:
            bindings = _writeback_bindings(pursuit)
        except (ContractError, FileNotFoundError) as exc:
            raise HTTPException(409, str(exc))
        files, refused = [], []
        for binding in bindings:
            try:
                files.append(_preview_one(pursuit, binding, _read_at(at)))
            # P2-30 (P26b-1): a StructureError (a ValueError) from the
            # write-back re-derivation is the parser's typed refusal —
            # a ragged buyer table — and lands as a lane refusal here
            # exactly as it already did on confirm.
            except (ContractError, FileNotFoundError, ValueError) as exc:
                refused.append({"lane": binding["lane"],
                                "file": binding["file"],
                                "reason": str(exc)})
        if not files:
            raise HTTPException(409, refused[0]["reason"] if refused
                                else "the container declares no "
                                     "deliverable")
        return {"files": files, "refused": refused}

    @app.post("/api/pursuits/{pursuit_id}/writeback/confirm")
    def writeback_confirm(pursuit_id: str, payload: dict,
                          who: str = Depends(operator)):
        """Runs EVERY declared lane under the one gate run; a per-lane
        refusal becomes a refused bundle entry while the others produce
        (absence RECORDED, the P18 row's law); 409 with no bundle only
        when every lane refused."""
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "writeback")
            try:
                # P25 item 8: every write-back lane is buyer-facing — the
                # bindings and the packaging block verify at the door
                # (P0-16, P0-20); per-slot pends are recorded in the facts
                assert_current(pursuit, lane="writeback")
                bindings = _writeback_bindings(pursuit)
            except (ContractError, FileNotFoundError) as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            files, refused = [], []
            for binding in bindings:
                try:
                    files.append(_run_one(pursuit, log, binding, at, who))
                except (ContractError, FileNotFoundError, ValueError) as exc:
                    # ValueError: python-docx/openpyxl refuse XML-incompatible
                    # text (P2-29a) — a RECORDED lane refusal, not a 500
                    refused.append({"lane": binding["lane"],
                                    "file": binding["file"],
                                    "reason": str(exc)})
            if not files:
                log.run_end(status="failed")
                raise HTTPException(409, refused[0]["reason"] if refused
                                    else "the container declares no "
                                         "deliverable")
            try:
                bundle = compose_bundle(pursuit, log, at=at,
                                        composed_by=who, refusals=refused)
            except ContractError as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
        return {"files": files, "bundle": bundle}

    # -- the hand-completion door (P26a item 1, P1-27; the owner's call) ---

    from engine.assembly.hand_fill import (
        catalogue as _hand_catalogue,
        read_hand_fill,
        write_hand_fill,
    )

    def _hand_context(pursuit) -> tuple[dict, str]:
        """The firm_default container + the template digest the plan was
        built against — the same binding the fill itself verifies."""
        frozen = pursuit.read_frozen("pursuit_plan")
        container = pursuit.read_artifact(
            frozen.get("slots_ref", "slots.json"))
        if container.get("source_mode") != "firm_default":
            raise ContractError(
                "hand completion is the firm_default lane — a buyer-provided "
                "target ships through write-back")
        try:
            ref_sha = pursuit.checkpoint_payload("path_b_outline").get(
                "reference_sha256")
        except FileNotFoundError:
            ref_sha = None
        if not ref_sha:
            raise ContractError(
                "no firm-template digest on record — plan against the "
                "firm template before entering values")
        return container, ref_sha

    @app.get("/api/pursuits/{pursuit_id}/writeback/hand-fill")
    def hand_fill_read(pursuit_id: str):
        """The record plus the owed catalogue: every slot a human
        completes, with its fields and whether it is filled — the
        reader remaining_by_hand never had."""
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        try:
            container, ref_sha = _hand_context(pursuit)
        except (ContractError, FileNotFoundError) as exc:
            raise HTTPException(409, str(exc))
        record = read_hand_fill(pursuit)
        values = (record.get("values", {}) if record
                  and record.get("template_sha256") == ref_sha else {})
        return {"record": record,
                "slots": _hand_catalogue(container, values)}

    @app.put("/api/pursuits/{pursuit_id}/writeback/hand-fill")
    def hand_fill_write(pursuit_id: str, payload: dict,
                        who: str = Depends(operator)):
        """Enter the values only a human supplies (metadata record,
        pricing grid, case block, inline line). Server-stamped: the
        session names entered_by and the server clock names at — a
        client `at` or `entered_by` is ignored (P0-11's rule). Last
        write wins per slot; an empty value clears a slot."""
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        values = payload.get("values")
        if not isinstance(values, dict):
            raise HTTPException(422, "values must be an object of "
                                     "slot_id -> value")
        with _mutate(pursuit_id):
            try:
                container, ref_sha = _hand_context(pursuit)
            except (ContractError, FileNotFoundError) as exc:
                raise HTTPException(409, str(exc))
            try:
                record = write_hand_fill(
                    pursuit, container=container, template_sha256=ref_sha,
                    entered_by=who, at=_at(payload), values=values)
            except ContractError as exc:
                raise HTTPException(422, str(exc))
        return {"record": record,
                "slots": _hand_catalogue(container, record["values"])}

    # -- share links with guest commenting (D16, Q1 override; c13b) --------

    from engine.intake.screen import screen_text
    from engine.web.share import ShareDenied, ShareLane

    def _share_lane(pursuit_id: str) -> ShareLane:
        _pursuit_root(pursuit_id)
        return ShareLane(PursuitDir(workspace, pursuit_id))

    @app.post("/api/pursuits/{pursuit_id}/share")
    def create_share(pursuit_id: str, payload: dict,
                     who: str = Depends(operator)):
        with _mutate(pursuit_id):  # P25 item 3 (P1-20): serialized
            lane = _share_lane(pursuit_id)
            try:
                return lane.create(created_by=who,
                                   label=payload.get("label", ""),
                                   expires_at=payload.get("expires_at", ""),
                                   at=_at(payload))
            except ShareDenied as exc:
                raise HTTPException(exc.status, exc.reason)

    @app.get("/api/pursuits/{pursuit_id}/share")
    def list_shares(pursuit_id: str, who: str = Depends(operator)):
        # operator-gated read: the listing carries the secret tokens the
        # creator hands to guests — auth material, not board data
        return _share_lane(pursuit_id).links()

    @app.post("/api/pursuits/{pursuit_id}/share/{link_id}/revoke")
    def revoke_share(pursuit_id: str, link_id: str, payload: dict,
                     who: str = Depends(operator)):
        with _mutate(pursuit_id):  # P0-13's residual gap (B104): serialized
            try:
                out = _share_lane(pursuit_id).revoke(
                    link_id=link_id, by=who, at=_at(payload))
            except ShareDenied as exc:
                raise HTTPException(exc.status, exc.reason)
        return {k: v for k, v in out.items() if k != "token"}

    def _resolve_share(token: str, at: str, action: str) -> tuple:
        """Find the link across pursuits — the token itself names its
        pursuit (scope is structural, not a parameter a guest supplies)."""
        for root in sorted(p for p in workspace.iterdir() if p.is_dir()):
            if not (root / "share" / "links.jsonl").exists():
                continue
            lane = ShareLane(PursuitDir(workspace, root.name))
            if any(r.get("token") == token
                   for r in lane._folded().values()):
                return lane, lane.resolve(token, at=at, action=action)
        raise ShareDenied(404, "unknown share link")

    @app.get("/share/{token}")
    def share_view(token: str, request: Request):
        # P27 wave 1: a browser navigating to the link gets the guest PAGE
        # — the static shell, served without resolving the token, so the
        # page's own JSON fetch (Accept: application/json) stays the one
        # access-logged view; every API caller keeps the JSON model
        if "text/html" in (request.headers.get("accept") or ""):
            return FileResponse(STATIC_DIR / "share.html")
        when = now()  # P25 item 4 (P0-18): a guest never supplies the clock
        try:
            lane, record = _resolve_share(token, when, "view")
        except ShareDenied as exc:
            raise HTTPException(exc.status, exc.reason)
        out = state_models.review(workspace, record["pursuit_id"],
                                  include_internal=False)
        if out is None:
            raise HTTPException(400, "nothing to review yet")
        out["share"] = {"link_id": record["link_id"],
                        "label": record["label"],
                        "expires_at": record["expires_at"]}
        # the guest's own comments (and any replies) render back to them
        pending = EventsLane(
            PursuitDir(workspace, record["pursuit_id"])).pending()
        out["your_comments"] = [
            {k: p.get(k) for k in ("cid", "section_id", "text",
                                   "display_name", "at")}
            for p in pending if p.get("link_id") == record["link_id"]]
        return out

    @app.post("/share/{token}/comments")
    def share_comment(token: str, payload: dict):
        when = now()  # P25 item 4 (P0-18): a guest never supplies the clock
        try:
            lane, record = _resolve_share(token, when, "comment")
        except ShareDenied as exc:
            raise HTTPException(exc.status, exc.reason)
        pursuit_id = record["pursuit_id"]
        display_name = " ".join(str(payload.get("display_name", "")
                                    ).split())[:60]
        text = str(payload.get("text", ""))
        if not display_name:
            lane.log_access(at=when, link_id=record["link_id"],
                            action="comment", granted=False,
                            detail="no display_name")
            raise HTTPException(422, "a display name is required")
        if not text.strip() or len(text) > 2000:
            lane.log_access(at=when, link_id=record["link_id"],
                            action="comment", granted=False,
                            detail="empty or over the 2000-char cap")
            raise HTTPException(422, "comment text must be 1-2000 chars")
        section_id = field(payload, "section_id", "str", default="")
        plan, sections = _plan_sections(pursuit_id)
        if section_id not in sections:
            lane.log_access(at=when, link_id=record["link_id"],
                            action="comment", granted=False,
                            detail=f"unknown section {section_id!r}")
            raise HTTPException(400, f"unknown section {section_id!r}")
        try:
            _slot_in_section(sections, section_id, payload.get("slot_id"))
        except HTTPException as exc:
            lane.log_access(at=when, link_id=record["link_id"],
                            action="comment", granted=False,
                            detail=f"slot not in section {section_id!r}")
            raise HTTPException(400, f"slot is not a slot of section "
                                     f"{section_id!r}") from exc
        flags = screen_text(text, source=f"share:{record['link_id']}")
        events_lane = EventsLane(PursuitDir(workspace, pursuit_id))
        with _mutate(pursuit_id):
            try:
                entry = events_lane.add_pending(
                    kind="comment", section_id=section_id,
                    # D16a: the PUBLIC id + self-declared name — the
                    # share: prefix IS the structural unverified marker
                    actor=f"share:{record['link_id']}:{display_name}",
                    actor_role="external_reviewer", at=when,
                    provenance="external",
                    slot_id=payload.get("slot_id"), text=text,
                    link_id=record["link_id"], display_name=display_name,
                    screen_flags=[{"pattern_id": f.pattern_id,
                                   "excerpt": f.excerpt} for f in flags])
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))
        return {"cid": entry["cid"], "section_id": section_id,
                "screened": bool(flags),
                "note": "visible to the pursuit team now; it reaches the "
                        "revision agent only if an internal reviewer "
                        "includes it"}

    @app.post("/api/pursuits/{pursuit_id}/comments/{cid}/include")
    def include_comment(pursuit_id: str, cid: str, payload: dict,
                        who: str = Depends(operator)):
        lane = _lane(pursuit_id)
        with _mutate(pursuit_id):
            try:
                return lane.mark_pending(cid, included_by=who,
                                         included_at=_at(payload))
            except (EventsError, ContractError) as exc:
                raise HTTPException(404, str(exc))

    @app.post("/api/pursuits/{pursuit_id}/comments/{cid}/dismiss")
    def dismiss_comment(pursuit_id: str, cid: str, payload: dict,
                        who: str = Depends(operator)):
        lane = _lane(pursuit_id)
        with _mutate(pursuit_id):
            try:
                return lane.mark_pending(cid, dismissed_by=who,
                                         dismissed_at=_at(payload))
            except (EventsError, ContractError) as exc:
                raise HTTPException(404, str(exc))

    # -- pings + gaps (D14/D15; c13) ---------------------------------------

    from engine.web.pings import PingError, PingLane, cross_pursuit_inbox

    def _ping_mutation(pursuit_id, payload, who, fn):
        """Ping actions are mini-runs writing the LIVE document + the gap
        run-log lines (the dormant B28(12) fields' writers). The document
        is the plan when one exists, else the brief (P15: intake gaps
        live at intake.gaps and are pingable pre-plan)."""
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "strategy")
            plan_path = pursuit.root / "plan.json"
            brief_path = pursuit.root / "brief.json"
            if plan_path.exists():
                doc, kind = (json.loads(plan_path.read_text(
                    encoding="utf-8")), "pursuit_plan")
            elif brief_path.exists():
                doc, kind = (json.loads(brief_path.read_text(
                    encoding="utf-8")), "bid_brief")
            else:
                log.run_end(status="failed")
                raise HTTPException(400, "no plan or brief yet — nothing "
                                         "carries gaps")
            lane = PingLane(pursuit)
            try:
                out = fn(lane, log, doc, at)
            except PingError as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            pursuit.write_artifact(kind, doc)  # live copy only
            log.run_end(status="completed")
        return out

    @app.post("/api/pursuits/{pursuit_id}/gaps")
    def open_gap(pursuit_id: str, payload: dict,
                 who: str = Depends(operator)):
        return _ping_mutation(
            pursuit_id, payload, who,
            lambda lane, log, plan, at: lane.open_gap(
                log, plan, section_id=payload.get("section_id", ""),
                question=payload.get("question", ""), at=at, actor=who))

    @app.post("/api/pursuits/{pursuit_id}/gaps/{gap_id}/ping")
    def ping_gap(pursuit_id: str, gap_id: str, payload: dict,
                 who: str = Depends(operator)):
        return _ping_mutation(
            pursuit_id, payload, who,
            lambda lane, log, plan, at: lane.ping(
                log, plan, gap_id=gap_id,
                route_to=payload.get("route_to", "sme"), at=at, actor=who))

    @app.post("/api/pursuits/{pursuit_id}/pings/{ping_id}/answer")
    def answer_ping(pursuit_id: str, ping_id: str, payload: dict,
                    who: str = Depends(operator)):
        return _ping_mutation(
            pursuit_id, payload, who,
            lambda lane, log, plan, at: lane.answer(
                log, plan, ping_id=ping_id,
                answer=payload.get("answer", ""), at=at, actor=who,
                propose_card=bool(payload.get("propose_card")),
                kb_root=kb_root))

    @app.get("/api/pursuits/{pursuit_id}/pings")
    def pursuit_pings(pursuit_id: str):
        _pursuit_root(pursuit_id)
        # P2-47: escalation is measured on the SERVER clock — a caller
        # cannot query a moment at which nothing looks overdue
        return PingLane(PursuitDir(workspace, pursuit_id)).inbox(at=now())

    @app.get("/api/pings")
    def ping_inbox():
        return cross_pursuit_inbox(workspace, at=now())

    # -- the review loop on the web (D6/D7, F9; c12) -----------------------

    @app.get("/api/pursuits/{pursuit_id}/review")
    def review_surface(pursuit_id: str, who: str = Depends(operator)):
        # P25 item 4 (P0-19): the FULL internal model — waiver identities,
        # pending internals, red-team findings — is for operators; guests
        # get the stripped surface through /share/{token}
        _pursuit_root(pursuit_id)
        out = state_models.review(workspace, pursuit_id)
        if out is None:
            raise HTTPException(
                400, "nothing to review yet — the surface renders the "
                     "validated annotated draft")
        return out

    def _revise_target(pursuit_id: str, at: str):
        def target(job: dict):
            from engine.kb import KBStore as _KBStore
            from engine.revision import run_round
            from engine.runlog import RunLogger as _RunLogger
            from engine.version import engine_version as _ver
            pursuit = PursuitDir(workspace, pursuit_id)
            store = _KBStore(kb_root)
            log = _RunLogger(pursuit.root, pursuit.new_run_id(),
                             pursuit.pursuit_id)
            caller = make_caller(log)
            cfg = effective_config(extra=extras("validation") or None)
            log.run_start(mode=mode, engine_version=_ver(), config=cfg,
                          kb_snapshot=store.snapshot(),
                          research_mode=cfg["research_mode"])
            report = run_round(
                pursuit, caller, log, store, at=at, actor=job["by"],
                should_cancel=lambda: bool(job.get("cancel")))
            log.run_end(status="completed")
            if report.status == "cancelled":
                return "done", ("cancelled — " + "; ".join(report.warnings))
            if report.status == "refused":
                from engine.contracts import ContractError
                raise ContractError("; ".join(report.warnings)
                                    or "round refused")
            return "done", (
                f"round {report.round_n}: revised "
                f"{', '.join(report.revised)}"
                + (f"; kept {', '.join(report.kept)}" if report.kept else "")
                + (f"; pended {', '.join(report.pended)}"
                   if report.pended else ""))
        return target

    @app.post("/api/pursuits/{pursuit_id}/revise")
    def revise(pursuit_id: str, payload: dict, who: str = Depends(operator)):
        _pursuit_root(pursuit_id)
        at = _at(payload)
        try:
            job = app.state.runner.submit(
                kind="revise", pursuit_id=pursuit_id, by=who, at=at,
                target=_revise_target(pursuit_id, at))
        except JobConflict as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse(job, status_code=202)

    @app.get("/api/pursuits/{pursuit_id}/revisions")
    def revisions(pursuit_id: str):
        root = _pursuit_root(pursuit_id)
        rev_dir = root / "revisions"
        out = []
        for record_path in sorted(rev_dir.glob("round_*.json")) \
                if rev_dir.exists() else []:
            out.append(json.loads(record_path.read_text(encoding="utf-8")))
        return out

    @app.get("/api/pursuits/{pursuit_id}/revisions/{n}")
    def revision_diff(pursuit_id: str, n: int):
        """The round record + the server-computed side-by-side texts
        (WP8): before from the archived rev{n-1} envelope, after from
        rev{n} (the archive, or the live envelope for the latest)."""
        root = _pursuit_root(pursuit_id)
        record_path = root / "revisions" / f"round_{n}.json"
        if not record_path.exists():
            raise HTTPException(404, f"no round {n}")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        before_path = root / "revisions" / f"draft.rev{n - 1}.json"
        after_path = root / "revisions" / f"draft.rev{n}.json"
        if not after_path.exists():
            after_path = root / "drafts" / "draft.json"

        def _prose_map(path):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            out = {}
            for entry in envelope.get("sections", []):
                for answer in entry.get("answers", []):
                    out[(entry["section_id"], answer.get("slot_id"))] = \
                        answer.get("prose", "")
                if entry.get("prose"):
                    out[(entry["section_id"], None)] = entry["prose"]
            return out

        before = _prose_map(before_path) if before_path.exists() else {}
        after = _prose_map(after_path)
        revised = {s["section_id"] for s in record.get("sections", [])
                   if s["outcome"] == "revised"}
        diff = []
        for key in sorted(after, key=lambda k: (k[0], str(k[1]))):
            section_id, slot_id = key
            if section_id not in revised:
                continue
            if before.get(key, "") != after[key]:
                diff.append({"section_id": section_id, "slot_id": slot_id,
                             "before": before.get(key, ""),
                             "after": after[key]})
        return {"record": record, "diff": diff}

    # -- gates on the web (D25; c10) ---------------------------------------

    from engine.contracts import ContractError
    from engine.kb import KBStore
    from engine.llm import effective_config
    from engine.planning import approve_gate2
    from engine.intake.gate import approve_gate0
    from engine.strategy.gate import approve_gate1
    from engine.validation.waiver import approve_waiver

    def _gate_run(pursuit, stage: str):
        """A mini-run for a human decision (D4): its own header/footer,
        NO caller — gates never call a model, and building one here would
        break the offline proof."""
        from engine.runlog import RunLogger
        from engine.version import engine_version
        store = KBStore(kb_root)
        log = RunLogger(pursuit.root, pursuit.new_run_id(),
                        pursuit.pursuit_id)
        cfg = effective_config(extra=extras(stage) or None)
        log.run_start(mode=mode, engine_version=engine_version(),
                      config=cfg, kb_snapshot=store.snapshot(),
                      research_mode=cfg["research_mode"])
        return log

    def _effort_payload(payload: dict, gate: str) -> dict | None:
        """The one-click effort confirm at gate close (D13): optional,
        and when present it follows the confirmed-retains-both rule.
        Validated BEFORE the decision commits (P25 item 1): a bad effort
        payload can never 422 after the gate has landed, which used to
        leave the next resubmit refusing an already-decided gate."""
        effort = payload.get("effort")
        if not effort:
            return None
        if not isinstance(effort, dict):
            raise HTTPException(422, "effort must be an object")
        effort = dict(effort)
        effort.setdefault("measurement", "confirmed")
        effort.setdefault("scope", "gate")
        effort.setdefault("gate", gate)
        if effort["measurement"] == "confirmed" and (
                "active_ms" not in effort
                or "confirmed_minutes" not in effort):
            raise HTTPException(
                422, "confirmed effort retains BOTH figures")
        return effort

    def _effort_append(lane: EventsLane, effort: dict | None, role: str,
                       who: str, at: str) -> None:
        """Appends the validated effort — only after a decision that
        actually landed; a converged resubmit records no second
        review_session (P25 item 1). The role is the session's (P27)."""
        if effort is None:
            return
        try:
            lane.append("review_session", at=at, actor=who,
                        actor_role=role, effort=effort)
        except (EventsError, ContractError) as exc:
            raise HTTPException(422, str(exc))

    def _preflight(root, brief: dict) -> dict | None:
        """The gate-time cost forecast (P15/C9): parse_workbook is pure
        code with zero model calls, so the DECLARED target (or first
        workbook) can be slot-counted EARLY; a brief-only pursuit falls
        back to matrix rows, labeled cruder by its unit name. A parse
        failure falls back too — the forecast must never block a gate."""
        from engine.pipeline.forecast import preflight_forecast
        slot_count = None
        try:
            resolved = _resolve_targets(root)
            from engine.structure import parse_target
            counts = [parse_target(t).slot_count
                      for t in resolved["targets"]]
            slot_count = sum(counts) if counts else None
        except Exception:  # noqa: BLE001 — fall back, never block a gate
            slot_count = None
        return preflight_forecast(
            slot_count=slot_count,
            matrix_rows=len(brief.get("requirements_matrix", [])))

    @app.get("/api/pursuits/{pursuit_id}/gate0")
    def gate0_model(pursuit_id: str):
        """The intake-review read model (P15): the assumption register,
        the open questions (origin marks the advisory questioner's — they
        gate nothing), and the red flags — in front of a human BEFORE
        research spends."""
        root = _pursuit_root(pursuit_id)
        brief_path = root / "brief.json"
        if not brief_path.exists():
            raise HTTPException(400, "no brief yet — advance first")
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        pursuit = PursuitDir(workspace, pursuit_id)
        intake = brief.get("intake", {})
        # P16: declared target roles vs the MODEL's response_structure —
        # a contradiction is shown HERE, pre-spend, where the register
        # correction fixes it (planning refuses as the backstop).
        conflicts = []
        try:
            resolved = _resolve_targets(root)
        except Exception as exc:  # noqa: BLE001 — surface, never 500
            conflicts.append(str(exc))
            resolved = {"targets": [], "declared": False}
        structure = brief.get("procurement", {}).get("response_structure")
        if resolved["declared"]:
            if resolved["targets"] and structure == "free_flow":
                conflicts.append(
                    f"{len(resolved['targets'])} document(s) declared "
                    "role=target but the intake model inferred free_flow — "
                    "correct response_structure on the register or withdraw "
                    "the target role (planning will refuse this "
                    "contradiction)")
            if not resolved["targets"] and structure in ("designated",
                                                         "mixed"):
                conflicts.append(
                    f"the intake model inferred {structure!r} but no "
                    "document is declared role=target — declare the "
                    "response vehicle or correct response_structure "
                    "(free-form routes to the firm template)")
        return {
            "decidable": "gate_0" not in pursuit.completed_stages(),
            "gate0": brief.get("gate0"),
            "assumptions": intake.get("assumptions", []),
            "gaps": intake.get("gaps", []),
            "documents": intake.get("documents", []),
            "red_flags": brief.get("procurement", {}).get("red_flags", []),
            "target_conflicts": conflicts,
            "buyer_name": brief.get("buyer", {}).get("name"),
            "forecast": _preflight(root, brief),
        }

    @app.post("/api/pursuits/{pursuit_id}/gate0")
    def gate0_decide(pursuit_id: str, payload: dict,
                     who: str = Depends(operator),
                     role: str = Depends(actor_role)):
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        effort = _effort_payload(payload, "gate_0")
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "gate_0")
            try:
                result = approve_gate0(
                    pursuit, log, decision=payload.get("decision", ""),
                    actor=who, at=at, notes=field(payload, "notes", "str"),
                    corrections=field(payload, "corrections", "list"),
                    answers=field(payload, "answers", "list"),
                    skips=field(payload, "skips", "list"),
                    wait_ms=field(payload, "wait_ms", "int", default=0),
                    kb_root=kb_root, org=payload.get("org"))
            except (ContractError, ValueError) as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
            if not result.converged:
                _effort_append(EventsLane(pursuit), effort, role, who, at)
        out = {"decision": result.decision, "converged": result.converged}
        if result.proposals:
            out["proposals"] = result.proposals  # steward inbox, not corpus
        return out

    @app.get("/api/pursuits/{pursuit_id}/gate1")
    def gate1_model(pursuit_id: str):
        root = _pursuit_root(pursuit_id)
        brief_path = root / "brief.json"
        if not brief_path.exists():
            raise HTTPException(400, "no brief yet — advance first")
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        themes = brief.get("win_themes", {})
        return {
            "status": brief.get("status"),
            "decidable": brief.get("status") == "gate1_pending",
            "candidates": themes.get("candidates", []),
            "approved": themes.get("approved", []),
            # P15-F2: intake writes flags to procurement.red_flags; the old
            # top-level read rendered every Gate-1 screen flagless — a
            # wired_for_incumbent finding was invisible at the bid/no-bid
            # decision it exists to inform.
            "red_flags": brief.get("procurement", {}).get("red_flags", []),
            "buyer_name": brief.get("buyer", {}).get("name"),
            "forecast": _preflight(root, brief),
        }

    @app.post("/api/pursuits/{pursuit_id}/gate1")
    def gate1_decide(pursuit_id: str, payload: dict,
                     who: str = Depends(operator),
                     role: str = Depends(actor_role)):
        root = _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        effort = _effort_payload(payload, "gate_1")
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "strategy")
            try:
                result = approve_gate1(
                    pursuit, log, decision=payload.get("decision", ""),
                    actor=who, at=at, notes=field(payload, "notes", "str"),
                    edits=field(payload, "edits", "dict"),
                    wait_ms=field(payload, "wait_ms", "int", default=0))
            except (ContractError, ValueError) as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
            if not result.converged:
                _effort_append(EventsLane(pursuit), effort, role, who, at)
        out = {"decision": result.decision, "converged": result.converged}
        # The collapse toggle (D25): gate 1 approved on the one-screen
        # path enqueues planning with an auto-gate-2 policy that fires
        # ONLY when nothing needs a human (B24: no open gap, no gapped
        # obligation is ever auto-disposed) — otherwise the job stops
        # awaiting_gate and the screen says why.
        if payload.get("collapse") and result.decision in (
                "approved", "approved_with_edits"):
            def collapsed_gate2(p):
                plan = p.read_artifact("plan.json")
                open_gaps = [g for s in plan.get("sections", [])
                             for g in s.get("gaps", [])
                             if g.get("status") in ("open", "pinged")]
                gapped = [o for o in plan.get("obligations", [])
                          if o["status"] == "gapped"]
                if open_gaps or gapped:
                    return None  # advance() treats None decider as stop
                return {"decision": "approved", "gates_collapsed": True}

            def collapse_target(job):
                pursuit_j = PursuitDir(workspace, pursuit_id)
                # The one resolver (P16/C5): the collapse job used to
                # hardcode glob order and ignore roles.json entirely.
                resolved_j = _resolve_targets(pursuit_j.root)
                adv = advance(
                    pursuit_j, make_caller=make_caller, mode=mode,
                    kb_root=kb_root, at=at, extras=extras,
                    targets=(resolved_j["targets"] if resolved_j["declared"]
                             else None),
                    core_doc=resolved_j["core"],
                    workbook=(None if resolved_j["declared"]
                              else next(iter(resolved_j["targets"]), None)),
                    decide_gate1=None, decide_gate2=None, actor=job["by"])
                if adv.status == "awaiting_gate" and \
                        adv.stopped_at == "gate_2":
                    decision = collapsed_gate2(pursuit_j)
                    if decision is None:
                        return "done", (
                            "awaiting_gate at gate_2 — the plan carries "
                            "open gaps or gapped obligations; the collapse "
                            "never auto-disposes a human decision (B24)")
                    log2 = _gate_run(pursuit_j, "planning")
                    approve_gate2(pursuit_j, log2, actor=job["by"], at=at,
                                  **decision)
                    log2.run_end(status="completed")
                    adv2 = advance(
                        pursuit_j, make_caller=make_caller, mode=mode,
                        kb_root=kb_root, at=at, extras=extras,
                        decide_gate1=None, decide_gate2=None,
                        actor=job["by"])
                    return "done", (f"collapsed gates: {adv2.status}"
                                    + (f" at {adv2.stopped_at}"
                                       if adv2.stopped_at else ""))
                return "done", f"{adv.status}" + (
                    f" at {adv.stopped_at}" if adv.stopped_at else "")

            try:
                job = app.state.runner.submit(
                    kind="advance", pursuit_id=pursuit_id, by=who, at=at,
                    target=collapse_target)
                out["job"] = job["id"]
            except JobConflict as exc:
                raise HTTPException(409, str(exc))
        return out

    @app.get("/api/pursuits/{pursuit_id}/gate2")
    def gate2_model(pursuit_id: str):
        """The Gate-2 modal content — the plan summary is ALWAYS shown
        (UAT C2: a blank modal means approving unseen)."""
        plan, sections = _plan_sections(pursuit_id)
        from engine.contracts import ContractError
        honesty = None
        try:  # the verified read (P0-2): a modal never renders an
            # unvouched freeze as the approved themes
            approved_themes = PursuitDir(workspace, pursuit_id).read_frozen(
                "bid_brief").get("win_themes", {}).get("approved", [])
        except FileNotFoundError:
            approved_themes = []
        except ContractError as exc:
            approved_themes = []
            honesty = f"frozen brief fails verification: {exc}"
        return {
            "status": plan.get("status"),
            "frozen_brief_honesty": honesty,
            "decidable": plan.get("status") == "gate2_pending",
            "path": plan.get("path"),
            "coverage_summary": plan.get("coverage_summary", {}),
            "themes_set": bool(approved_themes),
            "honesty": (None if approved_themes
                        else "NONE SET — drafting reads generic"),
            "sections": [
                {"section_id": s["section_id"], "title": s["title"],
                 "slot_count": len(s.get("slot_ids", [])),
                 "gaps": [
                     {"gap_id": g.get("gap_id"),
                      "slot_id": g.get("slot_id"), "kind": g.get("kind"),
                      "status": g.get("status"),
                      "question_to_human": g.get("question_to_human"),
                      # B24: the four options, NOTHING preselected
                      "options": ["answered", "omit_approved", "reframed",
                                  "draft_flagged"]}
                     for g in s.get("gaps", [])]}
                for s in plan.get("sections", [])],
            "obligations": plan.get("obligations", []),
        }

    @app.post("/api/pursuits/{pursuit_id}/gate2")
    def gate2_decide(pursuit_id: str, payload: dict,
                     who: str = Depends(operator),
                     role: str = Depends(actor_role)):
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        effort = _effort_payload(payload, "gate_2")
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "planning")
            try:
                result = approve_gate2(
                    pursuit, log, decision=payload.get("decision", ""),
                    actor=who, at=at, notes=field(payload, "notes", "str"),
                    edits=field(payload, "edits", "dict"),
                    wait_ms=field(payload, "wait_ms", "int", default=0),
                    gates_collapsed=bool(payload.get("gates_collapsed")))
            except (ContractError, ValueError) as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            log.run_end(status="completed")
            if not result.converged:
                _effort_append(EventsLane(pursuit), effort, role, who, at)
        return {"decision": result.decision, "converged": result.converged,
                "frozen": result.frozen_path is not None}

    @app.post("/api/pursuits/{pursuit_id}/waivers")
    def waive(pursuit_id: str, payload: dict, who: str = Depends(operator),
              role: str = Depends(actor_role)):
        _pursuit_root(pursuit_id)
        pursuit = PursuitDir(workspace, pursuit_id)
        at = _at(payload)
        claim_id = field(payload, "claim_id", "str", default="")
        reason = field(payload, "reason", "str", default="")
        if not claim_id or not reason:
            raise HTTPException(422, "claim_id and reason are required — "
                                     "the reason is the record")
        # the role is the session's, validated at sign-in — a waiver whose
        # event could not append would leave the record half-written, and
        # a declared session can only carry a declarable role (P27, M-9)
        with _mutate(pursuit_id):
            log = _gate_run(pursuit, "validation")
            try:
                result = approve_waiver(pursuit, log, claim_id=claim_id,
                                        actor=who, reason=reason, at=at)
            except (ContractError, ValueError) as exc:
                log.run_end(status="failed")
                raise HTTPException(409, str(exc))
            # P25 item 4 (P2-18): a refused waiver's mini-run says so
            log.run_end(status="completed" if result.status == "waived"
                        else "failed")
            if result.status == "waived":
                EventsLane(pursuit).append(
                    "waive_block", at=at, actor=who, actor_role=role,
                    claim_tier=payload.get("claim_tier"))
        if result.status == "refused":
            raise HTTPException(409, "; ".join(result.warnings))
        return {"status": result.status, "warnings": result.warnings}

    # -- the events lane (D5/D12/D13/D30) ----------------------------------

    from contextlib import contextmanager

    @contextmanager
    def _mutate(pursuit_id: str):
        """Plan-touching mutations serialize against the job lane: fast
        409 when busy, then the guard (with re-check) so a submission
        landing in the race window still cannot interleave."""
        running = runner.busy(pursuit_id)
        if running is not None:
            raise HTTPException(
                409, f"{running['kind']} {running['state']} for "
                     f"{pursuit_id} (job {running['id']}) — decide after "
                     "it finishes")
        with runner.guard(pursuit_id):
            running = runner.busy(pursuit_id)
            if running is not None:
                raise HTTPException(409, f"job {running['id']} started "
                                         "concurrently — retry")
            yield

    def _lane(pursuit_id: str) -> EventsLane:
        _pursuit_root(pursuit_id)
        return EventsLane(PursuitDir(workspace, pursuit_id))

    def _plan_sections(pursuit_id: str) -> dict:
        root = _pursuit_root(pursuit_id)  # P2-17: the shape check, one home
        plan_path = root / "plan.json"
        if not plan_path.exists():
            raise HTTPException(400, "no plan yet — comments target plan "
                                     "sections")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        return plan, {s["section_id"]: s for s in plan.get("sections", [])}

    def _slot_in_section(sections: dict, section_id: str, slot_id) -> None:
        """P3-14 (P26b-1, B112): a comment's slot_id must be one of ITS
        section's slots — a foreign slot would tag a later revision round
        onto the wrong target. None is fine (a section-level comment)."""
        if slot_id is None:
            return
        if not isinstance(slot_id, str) or \
                slot_id not in sections[section_id].get("slot_ids", []):
            raise HTTPException(
                400, f"slot {slot_id!r} is not a slot of section {section_id!r}")

    @app.post("/api/pursuits/{pursuit_id}/comments")
    def add_comment(pursuit_id: str, payload: dict,
                    who: str = Depends(operator),
                    role: str = Depends(actor_role)):
        at = _at(payload)  # P0-11: refused before any state is consulted
        section_id = field(payload, "section_id", "str", default="")
        plan, sections = _plan_sections(pursuit_id)
        if section_id not in sections:
            raise HTTPException(400, f"unknown section {section_id!r}")
        _slot_in_section(sections, section_id, payload.get("slot_id"))  # P3-14
        lane = _lane(pursuit_id)
        with _mutate(pursuit_id):
            try:
                entry = lane.add_pending(
                    kind=payload.get("kind", "comment"),
                    section_id=section_id, actor=who, actor_role=role,
                    at=at, slot_id=payload.get("slot_id"),
                    text=payload.get("text"),
                    before=payload.get("before"),
                    after=payload.get("after"),
                    edit_reason=payload.get("edit_reason"))
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))
            # D11: the first pending item puts a drafted section in_review
            # — on the LIVE plan only; the frozen copy never moves.
            section = sections[section_id]
            if section.get("draft_status") in ("drafted", "validated"):
                section["draft_status"] = "in_review"
                pursuit = PursuitDir(workspace, pursuit_id)
                pursuit.write_artifact("pursuit_plan", plan)
        return entry

    @app.get("/api/pursuits/{pursuit_id}/comments")
    def comments(pursuit_id: str):
        lane = _lane(pursuit_id)
        return {"pending": lane.pending(),
                "events": [e for e in lane.read()
                           if e["kind"] in ("comment", "edit", "accept",
                                            "reject")]}

    @app.delete("/api/pursuits/{pursuit_id}/comments/{cid}")
    def delete_comment(pursuit_id: str, cid: str,
                       who: str = Depends(operator)):
        lane = _lane(pursuit_id)
        with _mutate(pursuit_id):
            try:
                return lane.remove_pending(cid)
            except (EventsError, ContractError) as exc:
                raise HTTPException(404, str(exc))

    @app.post("/api/pursuits/{pursuit_id}/events")
    def add_event(pursuit_id: str, payload: dict,
                  who: str = Depends(operator),
                  role: str = Depends(actor_role)):
        with _mutate(pursuit_id):  # P25 item 3 (P1-20): serialized
            kind = payload.get("kind")
            if kind not in ("accept", "reject"):
                raise HTTPException(
                    422, "this door takes accept|reject of an agent revision; "
                         "comments/edits pend, outcome/effort have their own "
                         "routes")
            lane = _lane(pursuit_id)
            try:
                return lane.append(
                    kind, at=_at(payload), actor=who, actor_role=role,
                    section_id=payload.get("section_id"),
                    edit_reason=payload.get("edit_reason"))
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))

    @app.post("/api/pursuits/{pursuit_id}/accept")
    def accept_pursuit(pursuit_id: str, payload: dict,
                       who: str = Depends(operator),
                       role: str = Depends(actor_role)):
        """THE accept (D12): one pursuit-scoped event, no section_id —
        review_rounds_to_accept computes from it. Refuses while packaging
        is blocked: the Q2 control reaches the exit door."""
        root = _pursuit_root(pursuit_id)
        at = _at(payload)  # P0-11: refused before any state is consulted
        annotated_path = root / "drafts" / "annotated-draft.json"
        if not annotated_path.exists():
            raise HTTPException(409, "nothing to accept — the pursuit has "
                                     "no validated annotated draft")
        annotated = json.loads(annotated_path.read_text(encoding="utf-8"))
        if annotated.get("packaging", {}).get("blocked"):
            raise HTTPException(
                409, f"packaging is BLOCKED "
                     f"({annotated['packaging'].get('tier1_blocks', 0)} "
                     "tier-1 block(s)) — waive or revise before accepting")
        lane = _lane(pursuit_id)
        with _mutate(pursuit_id):
            try:
                event = lane.append(
                    "accept", at=at, actor=who, actor_role=role)
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))
            # D11: final is the pursuit-accept stamp — live plan only.
            plan_path = root / "plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            for section in plan.get("sections", []):
                if section.get("draft_status") in ("drafted", "validated",
                                                   "in_review"):
                    section["draft_status"] = "final"
            PursuitDir(workspace, pursuit_id).write_artifact(
                "pursuit_plan", plan)
            # P1-41: the flywheel turns here (the owner's call, B114 §2)
            # — the accept is durable above; what follows is reported,
            # never an un-accept.
            from engine.web.learn import learn_from_accept
            try:
                flywheel = learn_from_accept(workspace, kb_root, pursuit_id,
                                             at=at)
            except Exception as exc:  # noqa: BLE001 — surfaced in the body
                flywheel = {"error": f"{type(exc).__name__}: {exc}"}
        return {**event, "flywheel": flywheel}

    @app.post("/api/pursuits/{pursuit_id}/outcome")
    def record_outcome(pursuit_id: str, payload: dict,
                       who: str = Depends(operator),
                       role: str = Depends(actor_role)):
        with _mutate(pursuit_id):  # P25 item 3 (P1-20): serialized
            outcome = {k: payload[k] for k in
                       ("result", "buyer_feedback", "score_received")
                       if payload.get(k)}
            lane = _lane(pursuit_id)
            try:
                return lane.append("outcome", at=_at(payload), actor=who,
                                   actor_role=role, outcome=outcome)
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))

    @app.post("/api/pursuits/{pursuit_id}/effort")
    def record_effort(pursuit_id: str, payload: dict,
                      who: str = Depends(operator),
                      role: str = Depends(actor_role)):
        """D13: one event retains BOTH figures. confirmed requires the
        passive figure it was pre-filled from alongside the human's
        number; manual is the offline path; passive is the UI's own."""
        with _mutate(pursuit_id):  # P25 item 3 (P1-20): serialized
            measurement = payload.get("measurement", "passive")
            effort = {k: payload[k] for k in
                      ("active_ms", "measurement", "confirmed_minutes", "scope",
                       "gate", "started_at", "ended_at") if payload.get(k)
                      is not None}
            effort["measurement"] = measurement
            if measurement == "confirmed" and (
                    "active_ms" not in effort
                    or "confirmed_minutes" not in effort):
                raise HTTPException(
                    422, "confirmed effort retains BOTH figures — active_ms "
                         "(the passive measurement it was pre-filled from) and "
                         "confirmed_minutes (the human's number)")
            if measurement == "manual" and "confirmed_minutes" not in effort:
                raise HTTPException(422, "manual effort needs confirmed_minutes")
            if measurement == "passive" and "active_ms" not in effort:
                raise HTTPException(422, "passive effort needs active_ms")
            lane = _lane(pursuit_id)
            try:
                return lane.append("review_session", at=_at(payload), actor=who,
                                   actor_role=role, effort=effort)
            except (EventsError, ContractError) as exc:
                raise HTTPException(422, str(exc))

    # -- the steward assistant (P14/B63) -----------------------------------
    # Reads + the proposal door only, grounded in docs/steward + advisor.
    # Every route operator-gated — a share-link guest has no operator
    # cookie and gets the 401 for free. The caller seam mirrors the
    # advisor's: None by default (zero-spend FakeCaller), tests inject a
    # script, `serve --live-assistant` injects a LiveCaller (which itself
    # refuses without RFP_LIVE=1, B30(e)).

    from engine.assistant import (
        SESSION_CEILING_USD,
        AssistantLoopExhausted,
        AssistantSession,
        AssistantWireError,
        UnknownSession,
        run_turn,
    )
    from engine.assistant.session import MAX_MESSAGE_CHARS
    from engine.llm.caller import CostCeilingExceeded
    from engine.llm.config import effective_config

    assistant_fake = FakeCaller({})  # zero-spend default; tests inject
    app.state.assistant_caller = None
    app.state.assistant_mode = "dry_run"

    def _assistant_store():
        from engine.kb import KBStore
        return KBStore(kb_root)

    @app.post("/api/assistant/session")
    def assistant_session_mint(who: str = Depends(operator)):
        session = AssistantSession.mint(
            workspace, mode=app.state.assistant_mode,
            engine_version=engine_version(), config=effective_config(),
            kb_snapshot=_assistant_store().snapshot())
        return {"session_id": session.session_id,
                "ceiling_usd": SESSION_CEILING_USD,
                "spent_usd": session.spent_usd()}

    @app.get("/api/assistant/session/{session_id}")
    def assistant_session_read(session_id: str,
                               who: str = Depends(operator)):
        try:
            session = AssistantSession.load(workspace, session_id)
        except UnknownSession:
            raise HTTPException(404, f"no session {session_id!r}")
        return {"session_id": session.session_id,
                "transcript": session.transcript(),
                "ceiling_usd": SESSION_CEILING_USD,
                "spent_usd": session.spent_usd()}

    @app.get("/api/assistant/usage")
    def assistant_usage(who: str = Depends(operator)):
        """The lane reporting on itself (B64). Derive-never-store, like
        telemetry; None-until-first-use, like the advisor's cost lane —
        a lane nobody has used has no numbers, which is not the same as
        a lane that cost nothing."""
        from engine.assistant.usage import lane_usage
        return lane_usage(workspace) or {
            "note": "no assistant sessions yet",
            "ceiling_usd": SESSION_CEILING_USD,
            "cost_source": "assistant_lane"}

    @app.post("/api/assistant/session/{session_id}/message")
    def assistant_message(session_id: str, payload: dict,
                          who: str = Depends(operator)):
        try:
            session = AssistantSession.load(workspace, session_id)
        except UnknownSession:
            raise HTTPException(404, f"no session {session_id!r}")
        message = str(payload.get("message", "")).strip()
        if not 1 <= len(message) <= MAX_MESSAGE_CHARS:
            raise HTTPException(
                422, f"message must be 1-{MAX_MESSAGE_CHARS} characters")
        if session.spent_usd() >= SESSION_CEILING_USD:
            raise HTTPException(
                402, f"session ceiling ${SESSION_CEILING_USD:.2f} reached "
                     f"— start a new session to continue deliberately; "
                     f"the brake never silently truncates")
        caller = app.state.assistant_caller or assistant_fake
        try:
            result = run_turn(
                session, caller, store=_assistant_store(),
                workspace=workspace, records_provider=_workspace_records,
                message=message, who=who, at=_at(payload))
        except CostCeilingExceeded as exc:
            raise HTTPException(402, str(exc))
        except (AssistantWireError, AssistantLoopExhausted) as exc:
            raise HTTPException(502, f"assistant wire refused: {exc}")
        return {"reply": result.reply, "tool_trail": result.tool_trail,
                "screen_flags": result.screen_flags,
                "spent_usd": result.spent_usd,
                "ceiling_usd": SESSION_CEILING_USD}

    # -- the shell ---------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "app.html")

    return app
