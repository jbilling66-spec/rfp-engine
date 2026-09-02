"""P27 wave 1: the internal review model names the sections the latest
revision round revised (`last_round`), the ones an accept/reject of the
agent's revision applies to — read from round.py's own record keys
(`round_n`, `sections[].outcome`); None before any round; never on the
guest flavour. The outcome select's vocabulary equals the schema's."""

import json

from engine.web import state
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
