"""P27 wave 1 — source-level pins on the workbench shell.

There is no browser harness in this repo, so each test here proves that a
code path EXISTS in the shipped shell (a string, a handler, a fetch path),
never that it fires in a browser; behaviour is proven through the routes'
own web tests, and the owner's click-through before a pilot tag is the
one browser check this repo can make (B110). A test here that reads like
a behavioural claim is a defect (lessons.md)."""

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

