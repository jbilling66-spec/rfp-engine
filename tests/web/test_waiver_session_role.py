"""P27 wave 1 (M-9 through the waiver door): a waiver posts claim_id +
reason only; the waive_block event carries the SESSION's role and the
claim records the operator's name — no role travels in the payload."""

import json

from fastapi.testclient import TestClient

from engine.web.server import create_app
from tests.validation.fixtures.validations import (
    make_validation_script,
    run_validation_package,
)
from tests.web.conftest import FIXED_AT, raising_caller, sign_in


def test_waiver_records_the_session_role(tmp_path):
    pursuit, report, _ = run_validation_package(
        tmp_path, script=make_validation_script(plant_unsupported=True))
    assert report.blocked
    app = create_app(tmp_path, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Cam Contracts", role="contracts")
        pid = pursuit.pursuit_id
        marks = [k for s in client.get(f"/api/pursuits/{pid}/review").json()
                 ["sections"] for k in s["marks"] if k["mark"] == "block"]
        assert marks and marks[0]["claim_id"]   # the screen's own input
        r = client.post(f"/api/pursuits/{pid}/waivers", json={
            "claim_id": marks[0]["claim_id"],
            "reason": "Verified offline against the signed engagement letter."})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "waived"
        events = [json.loads(l) for l in
                  (pursuit.root / "events" / "events.jsonl")
                  .read_text(encoding="utf-8").splitlines()]
        waive = [e for e in events if e["kind"] == "waive_block"]
        assert len(waive) == 1
        assert waive[0]["actor_role"] == "contracts"
        assert waive[0]["actor"] == "Cam Contracts"
        after = pursuit.read_artifact("drafts/annotated-draft.json")
        claim = next(c for s in after["sections"]
                     for c in s.get("claims", [])
                     if c["claim_id"] == marks[0]["claim_id"])
        assert claim["waived_by"] == "Cam Contracts"
