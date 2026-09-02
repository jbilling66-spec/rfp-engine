"""P0-21 (P26a, session-36 sweep): a guest share view carries neither the
waiving operator's name nor the waiver reason — in the mark's LINE or
its detail — while the internal review still says who waived. The
pre-P26a test asserted only the KEY name, on a fixture with no waiver."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.validation import VALIDATION_NAME, approve_waiver
from engine.web.server import create_app
from tests.validation.fixtures.validations import (
    AT,
    make_validation_script,
    run_validation_package,
)
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

WAIVER_ACTOR = "Ola Ownerly"
WAIVER_REASON = "synthetic rationale: the source was verified offline"
EXPIRES = "2026-08-16T09:00:00"


@pytest.fixture(scope="module")
def waived_share(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("share-waiver")
    pursuit, report, log = run_validation_package(
        tmp, script=make_validation_script(plant_unsupported=True))
    assert report.blocked
    blocked = [c for s in pursuit.read_artifact(VALIDATION_NAME)["sections"]
               for c in s.get("claims", []) if c["disposition"] == "block"]
    result = approve_waiver(pursuit, log, claim_id=blocked[0]["claim_id"],
                            actor=WAIVER_ACTOR, reason=WAIVER_REASON, at=AT)
    assert result.status == "waived"
    log.run_end(status="completed")
    app = create_app(tmp, make_caller=raising_caller, now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Sharer")
        link = client.post(f"/api/pursuits/{pursuit.pursuit_id}/share", json={
            "label": "synthetic counsel", "expires_at": EXPIRES}).json()
        yield client, pursuit, link


def test_guest_view_carries_no_waiver_identity_or_reason(waived_share):
    client, pursuit, link = waived_share
    guest = TestClient(client.app, base_url="http://127.0.0.1")
    view = guest.get(f"/share/{link['token']}?at={FIXED_AT}")
    assert view.status_code == 200, view.text
    body = json.dumps(view.json())
    assert "waived" in body, "the waived mark itself is shown"
    assert WAIVER_ACTOR not in body
    assert WAIVER_REASON not in body
    assert "waived_by" not in body and "waiver_reason" not in body


def test_internal_review_still_names_the_waiver(waived_share):
    client, pursuit, _ = waived_share
    body = json.dumps(
        client.get(f"/api/pursuits/{pursuit.pursuit_id}/review").json())
    assert f"waived by {WAIVER_ACTOR}" in body
    assert WAIVER_REASON in body
