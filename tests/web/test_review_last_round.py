"""P27 wave 1: the internal review model names the sections the latest
revision round revised (`last_round`), the ones an accept/reject of the
agent's revision applies to — read from round.py's own record keys
(`round_n`, `sections[].outcome`); None before any round; never on the
guest flavour. The outcome select's vocabulary equals the schema's."""

import json

from fastapi.testclient import TestClient

from engine.web import state
from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller
from tests.validation.fixtures.validations import run_validation_package


def _plant_round(pursuit, n, outcomes):
    rev = pursuit.root / "revisions"
    rev.mkdir(exist_ok=True)
    (rev / f"round_{n}.json").write_text(json.dumps({
        "pursuit_id": pursuit.pursuit_id, "round_n": n,
        "sections": [{"section_id": s, "outcome": o, "warnings": []}
                     for s, o in outcomes.items()]}), encoding="utf-8")


def test_last_round_names_the_revised_sections(tmp_path):
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    ws, pid = tmp_path, pursuit.pursuit_id
    assert state.review(ws, pid)["last_round"] is None
    sections = [s["section_id"] for s in state.review(ws, pid)["sections"]]
    assert len(sections) >= 2
    _plant_round(pursuit, 1, {sections[0]: "revised", sections[1]: "kept"})
    _plant_round(pursuit, 2, {sections[0]: "kept", sections[1]: "revised"})
    assert state.review(ws, pid)["last_round"] == {"n": 2,
                                                   "revised": [sections[1]]}
    assert "last_round" not in state.review(ws, pid, include_internal=False)


def test_the_outcome_vocabulary_is_the_schemas():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "feedback-event.schema.json")
                        .read_text(encoding="utf-8"))
    enum = schema["properties"]["outcome"]["properties"]["result"]["enum"]
    js = (repo / "engine" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert f"OUTCOME_RESULTS = {json.dumps(enum)}" in js


def test_the_tenth_round_is_the_last_round(tmp_path):
    """W2b 1a (B136): `round_10` sorts before `round_2` by name — both
    the review model's `last_round` and the revisions list door must
    order rounds by NUMBER, or the tenth revision's accept/reject lands
    on the wrong sections and the history reads out of order."""
    pursuit, report, _ = run_validation_package(tmp_path)
    assert report.status == "complete"
    ws, pid = tmp_path, pursuit.pursuit_id
    sections = [s["section_id"] for s in state.review(ws, pid)["sections"]]
    for n in range(1, 11):
        # round n revises sections[n % 2] only, so the answer differs by n
        _plant_round(pursuit, n, {sections[0]: "revised" if n % 2 == 0 else "kept",
                                  sections[1]: "revised" if n % 2 == 1 else "kept"})
    assert state.review(ws, pid)["last_round"] == {"n": 10,
                                                   "revised": [sections[0]]}
    app = create_app(ws, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        rounds = client.get(f"/api/pursuits/{pid}/revisions").json()
    assert [r["round_n"] for r in rounds] == list(range(1, 11))
