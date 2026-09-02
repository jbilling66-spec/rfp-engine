"""Wrong-typed payload fields are 422s, never 500s (P26a Group A, P3-13).
Every guarded route gets the wrong shape for one field; the door names
the field and the shape it wanted. The helper itself is pinned first."""

import pytest
from fastapi import HTTPException

from engine.web.payload import field
from tests.web.conftest import FIXED_AT, sign_in


def test_field_reads_types_defaults_required_and_choices():
    assert field({"n": 3}, "n", "int") == 3
    assert field({}, "n", "int", default=0) == 0
    assert field({"s": "x"}, "s", "str", choices={"x", "y"}) == "x"
    with pytest.raises(HTTPException) as e:
        field({"n": True}, "n", "int")  # a bool is not an integer here
    assert e.value.status_code == 422
    assert "n must be an integer" in e.value.detail
    with pytest.raises(HTTPException) as e:
        field({}, "s", "str", required=True)
    assert "s is required" in e.value.detail
    with pytest.raises(HTTPException) as e:
        field({"s": "z"}, "s", "str", choices={"x"})
    assert "must be one of" in e.value.detail
    for bad, kind in ((7, "str"), ("x", "list"), ([], "dict"), ("1", "int")):
        with pytest.raises(HTTPException):
            field({"f": bad}, "f", kind)


@pytest.fixture
def client(offline_app):
    sign_in(offline_app)
    offline_app.post("/api/pursuits", json={"pursuit_id": "pur_types"})
    return offline_app


@pytest.mark.parametrize("method, path, payload, name", [
    ("post", "/api/pursuits", {"pursuit_id": 7}, "pursuit_id"),
    ("post", "/api/kb/proposals", {"kb_id": ["x"]}, "kb_id"),
    ("post", "/api/kb/proposals/merge", {"proposal_ids": "p"},
     "proposal_ids"),
    ("post", "/api/pursuits/pur_types/gate0",
     {"decision": "approved", "wait_ms": "soon"}, "wait_ms"),
    ("post", "/api/pursuits/pur_types/gate0",
     {"decision": "approved", "corrections": {"a": 1}},
     "corrections"),
    ("post", "/api/pursuits/pur_types/gate1",
     {"decision": "approved", "edits": ["x"]}, "edits"),
    ("post", "/api/pursuits/pur_types/gate2",
     {"decision": "approved", "notes": 5}, "notes"),
    ("post", "/api/pursuits/pur_types/waivers",
     {"claim_id": 1, "reason": "r"}, "claim_id"),
    ("post", "/api/pursuits/pur_types/comments",
     {"section_id": 3}, "section_id"),
])
def test_wrong_typed_fields_are_422_naming_the_field(client, method, path,
                                                     payload, name):
    r = getattr(client, method)(path, json=payload)
    assert r.status_code == 422, (r.status_code, r.text)
    assert name in r.json()["detail"]
