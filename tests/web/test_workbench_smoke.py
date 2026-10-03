"""P27 wave 2 (B134, W2a step 5): the headless workbench smoke test — the
machine half of the owner's click-through (B111 §5). The shell is loaded
in headless chromium against a live server over a seeded scratch
workspace: sign in, the board, the detail, every tab by deep link with
the sidebar highlight and the tab title checked, a dialog closed by Esc
with focus returned, Tab held inside a dialog, and zero console errors
or unhandled rejections across the whole walk — the CSP is in force, so
an inline-style regression surfaces here as a console violation.

The browser binary is not a wheel: when it is absent every browser test
SKIPS BY NAME (CONTRIBUTING says how to install it) and the one pin at
the bottom keeps CI honest — the workflow must install the browser, so
the skip never fires there. P0-22's lesson: the parse guard proves only
that the script parses; this proves it runs."""

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
INSTALL_HINT = ("chromium is not installed for playwright — run "
                "`.venv/bin/playwright install chromium` (CONTRIBUTING)")

TABS = (  # hash, view id suffix, sidebar data-view, document title
    ("#/pings", "pings", "pings", "Pings — RFP Engine"),
    ("#/kb", "kb", "kb", "Knowledge base — RFP Engine"),
    ("#/assistant", "assistant", "assistant", "Assistant — RFP Engine"),
    ("#/telemetry", "telemetry", "telemetry", "Telemetry — RFP Engine"),
    ("#/ops", "ops", "ops", "Operations — RFP Engine"),
    ("#/", "board", "board", "Pursuits — RFP Engine"),
)


@pytest.fixture(scope="module")
def walk(live_server):
    """One browser page for the whole module, with every console error
    and page error collected — the last test asserts the list is empty."""
    base, _ws = live_server
    errors: list[str] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:  # the binary, not the wheel
            pytest.skip(f"{INSTALL_HINT}: {exc.message.splitlines()[0]}")
        context = browser.new_context()
        page = context.new_page()
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        yield base, page, errors
        browser.close()


def test_the_shell_loads_under_its_csp_with_the_sign_in_dialog_focused(walk):
    base, page, _ = walk
    response = page.goto(base + "/")
    assert response is not None and response.ok
    csp = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    expect(page.locator("#opOverlay")).to_be_visible()
    assert page.evaluate("document.activeElement.id") == "opName"
    assert page.title() == "Pursuits — RFP Engine"


def test_signing_in_lands_on_the_board_with_the_seeded_pursuit(walk):
    base, page, _ = walk
    page.fill("#opName", "Robin Smoke")
    page.select_option("#opRole", "pursuit_lead")
    page.click("#opGo")
    expect(page.locator("#opOverlay")).to_be_hidden()
    row = page.locator("#boardRows .row", has_text="pur_smoke")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("gate_1")
    # P30a 3: the stage track on the row — one amber segment, the current
    expect(row.locator(".track .seg[data-state='current']")).to_have_count(1)

def test_the_board_filters_to_what_waits_on_a_person_and_sorts_by_station(walk):
    """P30a 5: three seeded pursuits — gate_1 (station 4), the reviewed
    one at gate_0 on the board (2), and a bare one at intake (1). The
    filter keeps the two paused on a person and drops the bare one; stage
    sort puts the bare one last, id sort puts it first. Every word is the
    server's: the station number, the stage, the count."""
    base, page, _ = walk
    expect(page.locator("#boardFilter")).to_have_text("waiting on you (2)")
    expect(page.locator("#boardCount")).to_have_text("3 of 3")
    ids = page.locator("#boardRows .row .id")
    expect(ids.last).to_have_text("pur_blank")           # stage: intake last
    page.select_option("#boardSort", "id")
    expect(ids.first).to_have_text("pur_blank")          # id: alphabetical
    page.click("#boardFilter")
    expect(page.locator("#boardCount")).to_have_text("2 of 3")
    expect(page.locator("#boardRows .row", has_text="pur_blank")).to_have_count(0)
    expect(page.locator("#boardFilter")).to_have_attribute("aria-pressed", "true")
    page.click("#boardFilter")
    expect(page.locator("#boardCount")).to_have_text("3 of 3")
    page.select_option("#boardSort", "stage")
    expect(ids.last).to_have_text("pur_blank")


@pytest.mark.parametrize("hash_, view, nav, title", TABS)
def test_every_tab_deep_links_lit_and_named(walk, hash_, view, nav, title):
    base, page, _ = walk
    page.evaluate(f"location.hash = {hash_!r}")
    expect(page.locator(f"#view-{view}")).to_have_class("view show")
    expect(page.locator("#mainNav a.active")).to_have_attribute("data-view", nav)
    expect(page).to_have_title(title)


def test_the_operations_view_reads_health_and_the_board(walk):
    """W2b 3: the composed view names the engine's version from the health
    door and lists the seeded pursuit from the board door."""
    from engine.version import VERSION
    base, page, _ = walk
    page.evaluate("location.hash = '#/ops'")
    expect(page.locator("#view-ops")).to_have_class("view show")
    expect(page.locator("#opsHealth")).to_contain_text(f"engine {VERSION}")
    expect(page.locator("#opsRows .row", has_text="pur_smoke")).to_have_count(1)
    expect(page).to_have_title("Operations — RFP Engine")


def test_the_detail_screen_renders_the_server_decided_actions(walk):
    base, page, _ = walk
    page.evaluate("location.hash = '#/pursuit/pur_smoke'")
    expect(page.locator("#view-detail")).to_have_class("view show")
    expect(page.locator("#detailTitle")).to_have_text("pur_smoke")
    expect(page.locator("#gate1Btn")).to_be_visible()   # the stage says gate_1
    expect(page.locator("#gate2Btn")).to_have_count(0)  # and nothing else
    expect(page.locator("label.upload")).to_be_visible()
    expect(page).to_have_title("pur_smoke — RFP Engine")
    expect(page.locator("#detailTrack .seg")).to_have_count(9)  # P30a 3
    # P30a 4: the rail — the server's next sentence, the station, the
    # decided gate, the actions inside the rail; the crumb names the pursuit
    expect(page.locator("#railStage")).to_have_text("Stage 4 of 9")
    expect(page.locator("#railNext")).to_contain_text("Gate 1")
    expect(page.locator("#railGates")).to_contain_text("decided by")
    expect(page.locator("#detailRail #gate1Btn")).to_be_visible()
    expect(page.locator("#crumbPid")).to_have_text("pur_smoke")


def test_a_dialog_opens_focused_closes_on_escape_and_returns_focus(walk):
    base, page, _ = walk
    page.click("#shareNewBtn")
    expect(page.locator("#shareOverlay")).to_be_visible()
    assert page.evaluate("document.activeElement.id") == "shLabel"
    assert page.get_attribute("#shareOverlay .modal", "role") == "dialog"
    page.keyboard.press("Escape")
    expect(page.locator("#shareOverlay")).to_be_hidden()
    assert page.evaluate("document.activeElement.id") == "shareNewBtn"


def test_tab_stays_inside_an_open_dialog(walk):
    base, page, _ = walk
    page.click("#gate1Btn")
    expect(page.locator("#gate1Overlay")).to_be_visible()
    for _ in range(12):
        page.keyboard.press("Tab")
        inside = page.evaluate(
            "document.getElementById('gate1Overlay').contains(document.activeElement)")
        assert inside, "focus left the open dialog"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate(
        "document.getElementById('gate1Overlay').contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(page.locator("#gate1Overlay")).to_be_hidden()


def test_the_sign_in_dialog_ignores_escape(walk):
    base, page, _ = walk
    # a fresh context has no session cookie: the dialog opens at boot and
    # is required — Esc must leave it where it is
    fresh = page.context.browser.new_context()
    try:
        other = fresh.new_page()
        other.goto(base + "/")
        expect(other.locator("#opOverlay")).to_be_visible()
        other.keyboard.press("Escape")
        expect(other.locator("#opOverlay")).to_be_visible()
        assert other.evaluate("document.activeElement.id") == "opName"
    finally:
        fresh.close()


def test_a_failed_door_is_a_toast_never_a_blank_view(walk):
    base, page, _ = walk
    # a pursuit that does not exist: the detail door 404s; the shell
    # shows the server's detail in a sticky toast and keeps the view.
    # On its own page (same context, same cookies): chromium logs the
    # deliberate 404 as a console error, which the walk's collector
    # must not see.
    other = page.context.new_page()
    try:
        other.goto(base + "/#/pursuit/pur_missing")
        expect(other.locator("#toast")).to_be_visible()
        expect(other.locator("#toast")).to_have_class("toast sticky")
        expect(other.locator("#toast")).to_contain_text("pur_missing")
        other.click("#toast")
        expect(other.locator("#toast")).to_be_hidden()
    finally:
        other.close()


def test_the_runs_panel_opens_a_run_and_filters_its_records(walk):
    """W2b 2: gate 0 left two runs on pur_smoke; the panel lists them,
    a click opens the records with the type filter, raw on demand."""
    base, page, _ = walk
    page.evaluate("location.hash = '#/pursuit/pur_smoke'")
    expect(page.locator("#view-detail")).to_have_class("view show")
    runs = page.locator("#runRows .runrow")
    assert runs.count() >= 2  # gate 0's advance, the re-advance, and their closes
    expect(runs.first).to_contain_text("run_")
    runs.first.click()
    expect(page.locator("#runRecords")).to_be_visible()
    records = page.locator("#runRecords .logrow")
    assert records.count() >= 1
    expect(records.first).to_contain_text("run_start")
    options = page.locator("#runKind option")
    assert options.count() > 1
    page.select_option("#runKind", "run_start")
    expect(page.locator("#runRecords .logrow[data-kind='run_start']").first).to_be_visible()
    hidden = page.locator("#runRecords .logrow:not([data-kind='run_start'])")
    if hidden.count():
        expect(hidden.first).to_be_hidden()
    page.select_option("#runKind", "")


def test_the_review_view_shows_rounds_and_a_diff(walk):
    """W2b 1b on the reviewed pursuit: Show rounds appears because the
    server names a last round; round 1 opens as before | after pairs."""
    base, page, _ = walk
    page.evaluate("location.hash = '#/review/pur_gapcase'")
    expect(page.locator("#view-review")).to_have_class("view show")
    expect(page.locator("#reviewTitle")).to_contain_text("revision 1")
    expect(page.locator("#roundsBtn")).to_be_visible()
    expect(page.locator("#reviewRounds")).to_be_hidden()  # nothing preselected
    page.click("#roundsBtn")
    rounds = page.locator("#reviewRounds .roundrow")
    expect(rounds).to_have_count(1)
    expect(rounds.first).to_contain_text("round 1")
    rounds.first.click()
    pairs = page.locator("#reviewRounds .diff-row")
    expect(pairs.first).to_be_visible()  # auto-waits for the diff door
    before = page.locator("#reviewRounds .diff-pair .prose").nth(0)
    after = page.locator("#reviewRounds .diff-pair .prose").nth(1)
    assert before.inner_text().strip() and after.inner_text().strip()
    assert before.inner_text() != after.inner_text()


def test_the_finish_panel_shows_each_buyer_files_hygiene(walk):
    """W2b 5 on the reviewed pursuit: Render documents composes the
    bundle; the buyer file lists with its hygiene line beneath it."""
    base, page, _ = walk
    page.evaluate("location.hash = '#/pursuit/pur_gapcase'")
    expect(page.locator("#view-detail")).to_have_class("view show")
    expect(page.locator("#detailFinish")).to_be_visible()
    page.click("#renderBtn")
    expect(page.locator("#finishDownloads a.dl").first).to_contain_text("response.docx")
    expect(page.locator("#finishDownloads .hygiene").first).to_contain_text("revision mark(s)")
    expect(page.locator("#finishDownloads .hygiene").first).to_contain_text("identity")


def test_accept_opens_the_learned_dialog_over_the_pursuit(walk):
    """W2b 4 on the reviewed pursuit — LAST of its tests, accept is
    irreversible: the learn report renders as a dialog over the pursuit
    the action lands on; Esc closes it like any dialog."""
    base, page, _ = walk
    page.evaluate("location.hash = '#/review/pur_gapcase'")
    expect(page.locator("#view-review")).to_have_class("view show")
    page.click("#acceptBtn")
    expect(page.locator("#learnedOverlay")).to_be_visible()
    expect(page.locator("#learnedOverlay .modal")).to_have_attribute("role", "dialog")
    assert page.locator("#learnedBody").inner_text().strip()
    assert page.evaluate("location.hash") == "#/pursuit/pur_gapcase"
    page.keyboard.press("Escape")
    expect(page.locator("#learnedOverlay")).to_be_hidden()
    expect(page.locator("#view-detail")).to_have_class("view show")


def test_the_walk_raised_no_console_errors_or_unhandled_rejections(walk):
    _base, _page, errors = walk
    assert errors == [], errors


def test_ci_installs_the_browser_so_the_skip_never_hides_there():
    """Not a browser test — never skipped. The workflow must carry the
    install step, or a missing binary would turn every test above into a
    silent skip on the one machine that matters."""
    workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
    assert ".venv/bin/playwright install --with-deps chromium" in workflow
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert ".venv/bin/playwright install chromium" in contributing
