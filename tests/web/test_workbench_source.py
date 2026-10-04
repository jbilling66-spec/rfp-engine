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
    assert overlays == 12  # W2b 4 (B136): + Learned; P30b 2 (B141): + the confirm dialog
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


def test_the_stylesheet_is_built_on_tokens():
    """P30a step 2 (B139): the shell's type and colour come from tokens
    on :root — system serif display + mono micro-labels, a six-step
    scale, tinted chips whose ink clears AA — so no rule outside :root
    carries a literal pixel font size, the mono stack is declared once,
    and a chip is never white-on-colour."""
    import re
    css = _css()
    for token in ("--font-display", "--font-mono", "--fs-xs", "--fs-sm",
                  "--fs-md", "--fs-base", "--fs-lg", "--fs-xl",
                  "--plan-tint", "--plan-ink", "--stop-tint", "--stop-ink"):
        assert f"{token}:" in css, token
    assert css.count("ui-monospace") == 1
    after_root = css[css.index("}", css.index(":root{")) + 1:]
    assert not re.findall(r"font(?:-size)?:\s*\d+px", after_root), "px font size outside :root"
    chip = css[css.index(".chip{"):css.index(".facts{")]
    assert "#fff" not in chip and "--plan-ink" in chip and "--stop-tint" in chip
    assert "var(--font-display)" in css[css.index("h1{"):css.index("button{")]


def test_the_shell_stage_order_is_the_servers():
    """P30a step 3 (B139): the stage track draws the server's nine
    stations — STAGE_ORDER in the shell equals state.PIPELINE, every
    station has a colour, and the track derives from the CURRENT stage
    (the server's word), never from checkpoint stems."""
    import re
    from engine.web import state
    js = _js()
    order = re.search(r"const STAGE_ORDER = \[(.*?)\];", js, re.S).group(1)
    assert re.findall(r'"([a-z_0-9]+)"', order) == list(state.PIPELINE)
    block = re.search(r"const STAGE_COLOR = \{(.*?)\};", js, re.S).group(1)
    assert set(state.PIPELINE) <= set(re.findall(r"(\w+):", block))
    assert "function stageTrack(" in js and 'data-state="' in js
    assert "completed_stages" not in js
    html, css = _html(), _css()
    assert 'id="detailTrack"' in html
    for sel in (".track", ".seg", ".lbl", '.seg[data-state="current"]'):
        assert sel in css, sel


def test_the_detail_rail_and_crumbs_are_in_the_shell():
    """P30a step 4 (B139): the detail's right rail — next, stage N of M,
    open gaps, the decided gates, the actions — sits first in DOM (tab
    order) and second on screen; a crumb trail replaces the back links
    on detail and review; every value is the server's."""
    html, js, css = _html(), _js(), _css()
    for i in ('id="detailRail"', 'id="railNext"', 'id="railStage"',
              'id="railGaps"', 'id="railGates"', 'id="crumbPid"',
              'id="reviewBack"'):
        assert i in html, i
    assert html.count('class="crumbs"') == 2 and 'class="back"' not in html
    assert (html.index('id="detailRail"') < html.index('id="detailActions"')
            < html.index('class="detail-main"'))
    assert "d.gates" in js and "Stage ${d.stage_n} of ${d.stage_count}" in js
    assert 'class="gate-row"' in js and "not yet" in js
    for sel in (".detail-grid", ".rail", ".rail-k", ".rail-next", ".crumbs",
                ".gate-row", ".detail-main"):
        assert sel in css, sel
    assert "max-width:1240px" in css
    # the look caught it: the sidebar's `nav a{display:block}` reached the
    # crumb trail and stacked it — the crumbs' own rule puts it back inline
    assert ".crumbs a{display:inline" in css


def test_the_board_sorts_and_filters_on_the_servers_words():
    """P30a step 5 (B139): the board names the buyer the server sends,
    sorts by the server's station number (pipeline order, furthest
    first; declined and corrupt last), by id, or by cost, and filters
    to the stages that wait on a person — a set pinned under the
    server's PIPELINE. The ops view sorts stage the same way, no longer
    alphabetically."""
    import re
    from engine.web import state
    html, js, css = _html(), _js(), _css()
    for i in ('id="boardSort"', 'id="boardFilter"', 'id="boardCount"',
              ">sort by<", ">waiting on you<"):
        assert i in html, i
    assert "function stageRank(" in js and "function renderBoard()" in js
    assert "r.buyer_name" in js and "r.stage_n" in js
    waiting = re.search(r"const WAITING = new Set\(\[(.*?)\]\)", js).group(1)
    assert set(re.findall(r'"([a-z_0-9]+)"', waiting)) <= set(state.PIPELINE)
    assert "localeCompare(String(b.stage))" not in js
    assert "stage: byStage" in js and "cost: byCost" in js
    for sel in (".toolbar", ".buyer"):
        assert sel in css, sel


# -- P30b (B141): behaviours + copy ------------------------------------------


def test_the_irreversible_actions_confirm_first():
    """Accept pursuit, Revoke a share link and Dismiss a guest comment
    each fired on one click (the 2026-10-02 scan, §3a items 7 and 8).
    One confirm dialog, opened through the W2a dialog pair, fronts all
    three with the action's own word on the go button — never a bare OK,
    never a native confirm(). Existence, not firing — the smoke test
    fires it on Accept and on Revoke."""
    html, js = _html(), _js()
    for needle in ('id="confirmOverlay"', 'id="confirmTitle"',
                   'id="confirmBody"', 'id="confirmGo"'):
        assert needle in html, needle
    assert "function confirmThen(title, body, word, fn" in js
    # the three callers, each inside its own handler's window
    i = js.index('$("acceptBtn").onclick')
    assert "confirmThen(" in js[i:i + 400] and '"Accept pursuit"' in js[i:i + 400]
    i = js.index('querySelectorAll(".shareRevoke")')
    assert "confirmThen(" in js[i:i + 400] and '"Revoke"' in js[i:i + 400]
    i = js.index('pend(".pendDismiss"')
    assert 'word: "Dismiss"' in js[i:i + 400]
    assert "confirmThen(ask.title, ask.body, ask.word" in js
    # no native confirm anywhere (the one-error-path rule's sibling)
    stripped = js.replace("confirmThen(", "").replace("confirmWriteback(", "")
    assert "confirm(" not in stripped
    # Revise keeps its solid weight only while something is pending
    assert 'classList.toggle("ghost", !m.sections.some(' in js


def test_the_actions_wait_while_the_server_names_a_live_job():
    """F5's remainder (B134 §1d): the buttons stayed live while a job
    ran, and the server 409'd the second click. Now the detail and the
    review payloads carry `job` (P30b 1) and the shell disables the
    pursuit's actions on that word; the clicked button waits from the
    click itself until the strip's terminal tick re-reads the detail.
    Nothing is hidden — the upload label stays a control; its input
    waits. Existence, not firing — the smoke test fires it."""
    js = _js()
    assert "function setBusy(job)" in js and "setBusy(d.job)" in js
    assert "#detailActions input" in js and "#finishActions button" in js
    assert "Boolean(m.job)" in js
    assert '$("advanceBtn").disabled = true;' in js
    assert '$("reviseBtn").disabled = true;' in js


def test_the_secondary_panels_fold_under_their_headings():
    """F8: Finish, Gaps and pings, Share for review, Outcome and Runs
    stacked as flat blocks and Outcome showed at every stage. Each is a
    `details.panel` whose summary wraps the SAME heading text (the
    guide's bold spans) plus a count the loaders fill; Finish stays open
    (it is the stage's work), Gaps opens while gaps are open, Outcome is
    rendered only once the pursuit is in review or declined and names
    the last recorded outcome. Existence, not firing."""
    import re
    html, js, css = _html(), _js(), _css()
    assert html.count('class="panel"') == 5
    for pid_ in ("detailFinish", "detailPings", "detailShares",
                 "detailOutcome", "detailRuns"):
        assert re.search(r'<details class="panel" id="%s"' % pid_, html), pid_
    for heading in (">Finish</h2>", ">Gaps and pings</h2>", ">Share for review</h2>",
                    ">Outcome</h2>", ">Runs</h2>"):
        assert heading in html, heading
    assert '<details class="panel" id="detailFinish" open' in html
    assert '<details class="panel" id="detailOutcome" hidden' in html
    for cid in ("finishCount", "gapsCount", "sharesCount", "outcomeCount", "runsCount"):
        assert f'id="{cid}"' in html, cid
    assert "d.outcome" in js and '["review", "declined"].includes(d.stage)' in js
    assert '$("detailPings").open = open.length > 0' in js
    assert ".panel>summary" in css and ".count{" in css


def test_the_first_run_banner_is_per_viewer_and_never_throws():
    """F9: nothing greeted a first sign-in before an empty board. The
    board carries a banner with the guide's three starting steps and the
    Assistant pointer, shown while a versioned per-viewer key is absent;
    Got it sets it. Every storage touch sits inside a try on the same
    line — a browser that blocks storage gets no banner, never a throw.
    It is not a board row (the count pins stay exact)."""
    html, js, css = _html(), _js(), _css()
    assert 'id="firstRun"' in html and 'id="firstRunGo"' in html
    assert html.index('id="firstRun"') < html.index('id="boardRows"')
    for step in ("+ New pursuit", "upload to inbox", "Advance", "Assistant", ">Got it<"):
        assert step in html, step
    assert 'const FIRST_RUN_KEY = "rfp.firstrun.v1";' in js
    touches = [line for line in js.splitlines() if "localStorage" in line]
    assert touches and all("try {" in line for line in touches), touches
    assert "function firstRunSeen()" in js and "firstRunSeen()" in js
    assert ".banner" in css
