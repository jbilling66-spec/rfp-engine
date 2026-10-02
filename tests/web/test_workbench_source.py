"""P27 wave 1 — source-level pins on the workbench shell.

Each test here proves that a code path EXISTS in the shipped shell (a
string, a handler, a fetch path), never that it fires in a browser;
behaviour is proven through the routes' own web tests and, since P27
wave 2 (B134), by tests/web/test_workbench_smoke.py, which drives the
shell in headless chromium; the owner's click-through before a pilot tag
stays the one HUMAN check (B110). A test here that reads like a
behavioural claim is a defect (lessons.md)."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "engine" / "web" / "static"
SERVER = Path(__file__).resolve().parents[2] / "engine" / "web" / "server.py"


def _js():
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _html():
    return (STATIC / "app.html").read_text(encoding="utf-8")


def test_the_shell_sends_no_hardcoded_role():
    """M-9: the shell never names a role; the picker is filled from the
    session door's `roles` list and the chosen value is posted at
    sign-in — nothing else in the shell mentions a role at all."""
    js = _js()
    assert "pursuit_lead" not in js
    assert "actor_role" not in js
    assert "ROLE(" not in js
    assert 's.roles' in js and '$("opRole")' in js
    assert 'role: $("opRole").value' in js
    assert 'id="opRole"' in _html()


def test_the_server_reads_no_role_from_a_payload():
    """Every role door depends on the session (Depends(actor_role)); the
    one remaining `payload.get("actor_role")` is the refusal in _at."""
    src = SERVER.read_text(encoding="utf-8")
    assert src.count('payload.get("actor_role")') == 1
    assert src.count("Depends(actor_role)") >= 9  # 3 gates + 6 event doors


def test_the_effort_producer_exists_in_the_shell():
    """P27 wave 1 (D13, the owner's call): the clock pauses on a hidden
    tab / blurred window and after the schema's 90 s idle figure; gate
    decisions carry active_ms AND confirmed_minutes (prefilled from the
    clock); leaving the review surface posts a passive review_session
    with keepalive. Existence of the paths, not their firing."""
    js = _js()
    assert '"visibilitychange"' in js and 'IDLE_MS = 90000' in js
    assert 'effort: gateEffort("g0Minutes")' in js
    assert 'effort: gateEffort("g1Minutes")' in js
    assert 'effort: gateEffort("g2Minutes")' in js
    assert "confirmed_minutes: typed === \"\" ? Math.round(ms / 60000)" in js
    assert 'measurement: "passive"' in js and "keepalive: true" in js
    assert 'scope: "pursuit", gate: "review_loop"' in js
    assert "flushReviewEffort" in js and "ms < 5000" in js
    html = _html()
    for n in "012":
        assert f'id="g{n}Minutes"' in html
    assert "Minutes on this gate" in html


def test_the_finish_panel_reaches_its_doors_and_is_server_gated():
    """P27 wave 1 (the curl doors retired): render, the two literal
    download headings, write-back preview → confirm as two steps, the
    hand-completion form with its add-row editor. The panel keys on the
    server's `finishing` model. Existence of the paths, not their firing."""
    js, html = _js(), _html()
    assert "f.reviewable" in js and "f.hand_fill_lane" in js
    assert "Render documents" in js and "/export`" in js
    assert "To the buyer" in js and "Internal — do not send" in js
    assert "/downloads`" in js and "/download/${encodeURIComponent(name)}" in js
    assert "Preview write-back" in js and "/writeback/preview`" in js
    assert "Confirm write-back" in html and "/writeback/confirm`" in js
    # confirm is enabled only inside the preview handler — two steps
    assert '$("wbConfirm").disabled = false' in js
    assert "Complete by hand" in js and "/writeback/hand-fill`" in js
    assert 'method: "PUT"' in js and "Add row" in js and "Save values" in html


def test_the_waiver_screen_reaches_its_door_from_block_marks():
    """P27 wave 1: a BLOCK mark carrying a claim id offers Waive; the
    overlay posts claim_id + reason and surfaces the server's warnings.
    Existence of the path, not its firing."""
    js, html = _js(), _html()
    assert 'k.mark === "block" && k.claim_id' in js
    assert ">Waive</button>" in js and "/waivers`" in js
    assert "claim_id: claimId, reason:" in js
    assert 'id="waiverOverlay"' in html and "Confirm waiver" in html


def test_the_ping_inbox_reaches_its_five_doors():
    """P27 wave 1: the Pings tab (cross-pursuit), the pursuit's own inbox,
    ping an SME on an open gap (route chosen, nothing preselected), answer
    with the propose-a-card box, open a gap. Existence, not firing."""
    js, html = _js(), _html()
    assert '"/api/pings"' in js and "/pings`" in js
    assert "/ping`" in js and "/answer`" in js and "/gaps`" in js
    assert 'href="#/pings"' in html and 'id="view-pings"' in html
    assert "Ping an SME" in js and "Answer" in js and "Open a gap" in html
    assert 'value="">— route to —</option>' in js
    assert "propose_card:" in js and "escalated" in js


def test_the_review_loop_doors_are_reached():
    """P27 wave 1 (the owner's call): guest pendings offer Include /
    Dismiss (with the injection-screen flag shown), internal pendings
    Withdraw, sections the last round revised offer Accept / Reject
    revision, the header offers Accept pursuit, the detail screen records
    the outcome from the schema's own result vocabulary. Existence, not
    firing."""
    js, html = _js(), _html()
    assert 'p.provenance === "external"' in js
    assert ">Include</button>" in js and ">Dismiss</button>" in js
    assert ">Withdraw</button>" in js and 'method: "DELETE"' in js
    assert "/include`" in js and "/dismiss`" in js
    assert "m.last_round.revised.includes(s.section_id)" in js
    assert "Accept revision" in js and "Reject revision" in js and "/events`" in js
    assert "Accept pursuit" in html and "/accept`" in js
    assert "Record outcome" in html and "/outcome`" in js
    assert 'OUTCOME_RESULTS = ["won", "lost", "shortlisted", "withdrawn", "no_decision"]' in js
    assert "flagged by the injection screen" in js


# -- P27 wave 2, W2a step 1 (B134): shell hygiene ---------------------------

# class tokens the script uses only as selectors (querySelectorAll hooks);
# they carry no style and need no rule — every other token must have one
HOOK_CLASSES = frozenset({
    "cmt", "cmtGo", "g0ans", "g0fix", "g0skip", "g1kill", "g2dispose",
    "g2note", "g2waive", "g2waivenote", "hfrows", "hfv", "pendDismiss",
    "pendInclude", "pendWithdraw", "pingAnswer", "pingBtn", "pingGo",
    "pingPropose", "revAccept", "revReject", "routeTo", "shareCopy",
    "shareRevoke", "waiveBtn",
})


def _css():
    return (STATIC / "app.css").read_text(encoding="utf-8")


def test_the_shell_carries_no_inline_style():
    """The CSP is default-src 'self' with no unsafe-inline, so a style
    attribute never renders — the upload label shipped unstyled for six
    pilot tags. Every control is styled from app.css."""
    assert 'style="' not in _js()
    assert 'style="' not in _html()


def test_every_class_the_shell_uses_has_a_rule():
    """A class with no rule is a ghost (`muted` had eighteen uses and no
    rule). Tokens from class="…" in the shell and from classList calls,
    minus the selector-only hooks, each match a `.name` selector."""
    import re
    tokens = set()
    for src in (_html(), _js()):
        for m in re.finditer(r'class="([^"]*)"', src):
            tokens.update(t for t in m.group(1).split()
                          if re.fullmatch(r"[A-Za-z][\w-]*", t))
    tokens.update(re.findall(r'classList\.(?:toggle|add)\("([\w-]+)"', _js()))
    css = _css()
    ghosts = sorted(t for t in tokens - HOOK_CLASSES
                    if not re.search(r"\." + re.escape(t) + r"(?![\w-])", css))
    assert not ghosts, ghosts
    # the allowlist is exact: a hook that gained a rule leaves the list
    styled_hooks = sorted(t for t in HOOK_CLASSES
                          if re.search(r"\." + re.escape(t) + r"(?![\w-])", css))
    assert not styled_hooks, styled_hooks


def test_the_stage_colors_cover_every_stage_the_server_names():
    """The server decides the stage (state.py); the shell only colours it.
    Every literal `_stage_and_next` can return, plus the `corrupt`
    override, has a STAGE_COLOR entry — an unknown stage fell through to
    plan-blue, so a corrupt pursuit read as healthy."""
    import re
    state = (SERVER.parent / "state.py").read_text(encoding="utf-8")
    stages = set(re.findall(r'return "([a-z_0-9]+)",', state)) | {"corrupt"}
    block = re.search(r"const STAGE_COLOR = \{(.*?)\};", _js(), re.S).group(1)
    keys = set(re.findall(r"(\w+):", block))
    assert stages <= keys, sorted(stages - keys)
    assert 'corrupt: "stop"' in block


# -- P27 wave 2, W2a step 2 (B134): one error path; the sidebar follows ----

GUARDED_ENTRY_POINTS = (
    "routeFromHash", "bootSession", "openGate0", "openGate1", "openGate2",
    "uploadFile", "decideProposal", "loadShares", "loadReview", "loadKb",
    "loadTelemetry",
)


def test_the_shell_has_one_error_path():
    """A failed load used to leave a blank view (401) or an unhandled
    rejection; one alert() and three bare `.then(r => r.json())` fetches
    bypassed api(). Now api() throws a typed ApiError and every entry
    point is wrapped: 401 reopens the sign-in dialog, anything else is a
    sticky toast carrying the server's detail. Existence, not firing."""
    js = _js()
    assert js.count("alert(") == 0
    assert js.count(".then((r) => r.json())") == 0
    assert "class ApiError extends Error" in js
    assert "e.status === 401" in js and "function guarded(fn)" in js
    for name in GUARDED_ENTRY_POINTS:
        assert f"{name} = guarded({name});" in js, name
    # the raw upload keeps its wire shape: no JSON header on a PUT body
    assert "raw: true" in js and 'headers: raw ? {} :' in js


def test_the_sidebar_and_title_follow_the_hash():
    """A deep link to #/kb left "Pursuits" lit and the tab titled by the
    static <title>: the highlight was set only by the click handler.
    routeFromHash now names the view and the title on every route."""
    js = _js()
    assert "function setNav(view, title)" in js
    assert "a.dataset.view === view" in js and "document.title = " in js
    for view in ("board", "pings", "kb", "assistant", "telemetry", "ops"):
        assert f'setNav("{view}"' in js, view
    assert "x.classList.toggle(\"active\", x === a)" not in js


# -- P27 wave 2, W2a step 3 (B134): the job strip survives --------------------

def test_the_job_strip_resumes_and_cancels():
    """A reload lost the strip (no jobs fetch at boot) and a failed poll
    left it alive forever (no error path in the tick). Boot re-attaches
    to a live job from the jobs list; three failed ticks give up by name;
    Cancel renders on the server's `cancellable`. Existence, not firing."""
    js, html = _js(), _html()
    assert '"/api/jobs"' in js and "function resumeJobs()" in js
    assert "/cancel`" in js and 'method: "POST"' in js
    assert ">Cancel</button>" in html and 'id="jobCancel"' in html
    assert "job.cancellable" in js
    assert "JOB_FAILS" in js and "++JOB_FAILS < 3" in js
    assert "reload to re-attach" in js


# -- P27 wave 2, W2a step 4 (B134): dialogs are dialogs ---------------------

def test_every_dialog_has_its_semantics_and_one_opener():
    """Ten overlays shipped as bare divs: no role, no label, no Esc, no
    focus trap, focus never returned. Every modal now carries
    role=dialog / aria-modal / aria-labelledby, and one openDialog /
    closeDialog pair owns focus; the sign-in dialog ignores Esc because
    it is required. Existence, not firing — the smoke test fires it."""
    html, js = _html(), _js()
    overlays = html.count('class="overlay"')
    assert overlays == 11  # W2b 4 (B136): + the Learned dialog
    assert html.count('role="dialog"') == overlays
    assert html.count('aria-modal="true"') == overlays
    assert html.count('aria-labelledby="') == overlays
    assert 'Overlay").hidden = false' not in js
    assert 'Overlay").hidden = true' not in js
    assert "function openDialog(id)" in js and "function closeDialog(id)" in js
    assert 'e.key === "Escape"' in js and 'e.key !== "Tab") return;' in js
    assert 'ov.id === "opOverlay"' in js
    assert 'role="status"' in html and html.count('aria-live="polite"') >= 2


# -- P27 wave 2, W2b (B136): the three screens -------------------------------

def test_the_rounds_view_reaches_both_revisions_doors():
    """W2b 1b: the review header offers Show rounds only when the server
    names a last round; the list reaches the rounds door, a round reaches
    the diff door, and a pair renders before | after as text. Existence,
    not firing — the smoke walk opens it on the seeded reviewed pursuit."""
    js, html, css = _js(), _html(), _css()
    assert 'id="roundsBtn"' in html and ">Show rounds<" in html
    assert 'id="reviewRounds"' in html
    assert "/revisions`" in js and "/revisions/${" in js
    assert "!m.last_round" in js  # the server's word, not a client guess
    assert 'class="diff-pair"' in js and ".diff-pair" in css
    assert "no text changed in this round" in js


def test_the_runs_panel_reaches_both_runs_doors():
    """W2b 2: the detail view lists the pursuit's runs and opens one as
    its raw records with a type filter and a raw toggle — the back-end
    human's view (B113 §10a). The shell renders what the door returns
    and writes nothing. Existence, not firing — the smoke walk opens the
    panel on the seeded pursuit's two runs."""
    js, html, css = _js(), _html(), _css()
    assert 'id="detailRuns"' in html and ">Runs<" in html
    assert 'id="runKind"' in html and 'id="runRecords"' in html
    assert "/runs`" in js and "/runs/${" in js
    assert "function runSummary(r)" in js and 'case "error":' in js
    assert "<summary>raw</summary>" in js
    assert ".logrow" in css
    # the viewer never writes: no POST/PUT/DELETE near the runs doors
    body = js[js.index("async function loadRuns"):js.index("// -- the revision history")]
    assert "method:" not in body


def test_the_operations_view_is_composed_from_three_existing_doors():
    """W2b 3: #/ops reads the board, the jobs journal and the health line
    and composes the cross-pursuit view in the browser — no new server
    door, no stored "attention" state. Existence, not firing — the smoke
    walk deep-links it and reads the health line and the seeded row."""
    js, html, css = _js(), _html(), _css()
    assert 'href="#/ops"' in html and 'id="view-ops"' in html
    assert ">Operations<" in html and ">needs attention<" in html
    assert 'id="opsSort"' in html and 'id="opsHealth"' in html
    assert '"/api/health"' in js and '"/api/pursuits"' in js and '"/api/jobs"' in js
    assert "async function loadOps()" in js and "function renderOps()" in js
    assert "OPS_QUIET_RUNS" in js
    assert ".attn" in css


def test_the_learn_report_renders_as_a_dialog():
    """W2b 4 (B122 §9c): accept and write-back confirm read the response's
    `flywheel` report into the Learned dialog — routed, proposals, signals,
    skipped with reasons, withheld as counts (never the matched text), the
    typed error. The fixed toast no longer drops it. Existence, not firing
    — the smoke walk accepts the seeded reviewed pursuit and reads it."""
    js, html, css = _js(), _html(), _css()
    assert 'id="learnedOverlay"' in html and ">Learned<" in html
    assert "function learnedLines(report)" in js and "function showLearned(report)" in js
    assert js.count("showLearned(out.flywheel)") == 2  # accept + write-back confirm
    assert "report.skipped" in js and "report.blocked" in js and "report.error" in js
    assert "n(b.locations)" in js  # a count of locations, never their text
    assert "b.locations.map" not in js and "b.locations.join" not in js
    assert ".learn-skip" in css


def test_the_finish_panel_renders_hygiene_and_stale():
    """W2b 5: under each buyer file the shell shows the bundle's hygiene
    line, and a withheld entry whose status is drifted carries the stale
    chip — by the door's field, never by parsing the reason."""
    js, css = _js(), _css()
    assert "dl.hygiene" in js and "revision mark(s)" in js and "comment part(s)" in js
    assert 'r.status === "drifted"' in js and ">stale</span>" in js
    assert "hygiene not recorded" in js
    assert ".hygiene" in css
