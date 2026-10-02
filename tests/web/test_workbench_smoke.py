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
    expect(page.locator("#boardRows .row").first).to_contain_text("pur_smoke")
    expect(page.locator("#boardRows .row").first).to_contain_text("gate_1")


@pytest.mark.parametrize("hash_, view, nav, title", TABS)
def test_every_tab_deep_links_lit_and_named(walk, hash_, view, nav, title):
    base, page, _ = walk
    page.evaluate(f"location.hash = {hash_!r}")
    expect(page.locator(f"#view-{view}")).to_have_class("view show")
    expect(page.locator("#mainNav a.active")).to_have_attribute("data-view", nav)
    expect(page).to_have_title(title)


def test_the_detail_screen_renders_the_server_decided_actions(walk):
    base, page, _ = walk
    page.evaluate("location.hash = '#/pursuit/pur_smoke'")
    expect(page.locator("#view-detail")).to_have_class("view show")
    expect(page.locator("#detailTitle")).to_have_text("pur_smoke")
    expect(page.locator("#gate1Btn")).to_be_visible()   # the stage says gate_1
    expect(page.locator("#gate2Btn")).to_have_count(0)  # and nothing else
    expect(page.locator("label.upload")).to_be_visible()
    expect(page).to_have_title("pur_smoke — RFP Engine")


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
