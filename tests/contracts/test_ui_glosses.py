"""P30b 6 (B141): the copy pass's two glossaries are pinned to the server
enums they render. Gate 2's disposition menu shows the advisor doc's
words over the planning gate's action values; the job strip and its
terminal toast add one line in the user's words to each terminal job
state while keeping the state word itself. A key the server does not
know, or a server value the shell has no words for, is a drift. The
rationale-voice strings the scan named (§3a item 10) stay gone."""

import re
from pathlib import Path

from engine.planning.gate import _ACTIONS
from engine.web.jobs import _STATES

STATIC = Path(__file__).resolve().parents[2] / "engine" / "web" / "static"
TERMINAL = frozenset(_STATES) - {"queued", "running"}


def _js():
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _keys(name: str) -> set[str]:
    m = re.search(r"const %s = \{(.*?)\};" % name, _js(), re.S)
    assert m, f"{name} is not in the shell"
    return set(re.findall(r"^\s*(\w+):", m.group(1), re.M))


def test_the_disposition_labels_cover_the_planning_gates_actions():
    assert _keys("DISPOSITION_LABEL") == set(_ACTIONS)
    js = _js()
    assert "DISPOSITION_LABEL[o] || o" in js  # the value stays the enum
    assert "the human disposes" not in js


def test_the_job_state_glosses_cover_every_terminal_state():
    assert _keys("STATE_GLOSS") == TERMINAL
    js = _js()
    assert "function stateWord(state)" in js
    # the state word itself survives the gloss (the record's word first)
    assert "${state}${STATE_GLOSS[state]" in js


def test_the_rationale_voice_left_the_user_copy():
    html = (STATIC / "app.html").read_text(encoding="utf-8")
    for gone in ("nothing is preselected", "it is the record",
                 "the reason is the record", "is never preselected"):
        assert gone not in html, gone
    assert "waived — on the record" not in _js()
