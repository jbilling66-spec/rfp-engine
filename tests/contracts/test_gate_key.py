"""The gate-decision request digest (P25 item 1): the key is WHAT was
decided, canonicalised — never the clock or per-submission transport."""

import pytest

from engine.contracts import request_digest, same_request


def test_digest_is_canonical_over_order_none_and_empties():
    a = request_digest(decision="approved", notes=None, edits=None)
    b = request_digest(edits={"dispose": []}, decision="approved")
    c = request_digest(decision="approved", notes="")
    assert a == b == c
    assert len(a) == 64
    assert request_digest(decision="approved", notes="x") != a
    assert request_digest(decision="approved_with_edits") != a
    assert request_digest(decision="approved", gates_collapsed=False) == a
    assert request_digest(decision="approved", gates_collapsed=True) != a
    nested = request_digest(decision="approved", edits={
        "dispose": [{"gap_id": "g1", "action": "answered", "note": None}]})
    assert nested == request_digest(decision="approved", edits={
        "dispose": [{"action": "answered", "gap_id": "g1"}]})


def test_digest_refuses_transport_fields():
    for bad in ({"at": "2026-08-09T09:00:00"}, {"wait_ms": 3},
                {"effort": {}}, {"actor_role": "pursuit_lead"}):
        with pytest.raises(ValueError, match="non-semantic"):
            request_digest(decision="approved", **bad)


def test_same_request_semantics():
    d = request_digest(decision="approved")
    ckpt = {"decision": "approved", "actor": "pat", "request_sha256": d}
    assert same_request(ckpt, decision="approved", actor="pat", digest=d,
                        actor_key="actor")
    assert not same_request(ckpt, decision="rejected", actor="pat",
                            digest=d, actor_key="actor")
    assert not same_request(ckpt, decision="approved", actor="sam",
                            digest=d, actor_key="actor")
    assert not same_request(ckpt, decision="approved", actor="pat",
                            digest="0" * 64, actor_key="actor")
    # a pre-P25 record carries no digest: (decision, actor) alone
    legacy = {"decision": "approved", "actor": "pat", "at": "t"}
    assert same_request(legacy, decision="approved", actor="pat",
                        digest="0" * 64, actor_key="actor")
    stamp = {"approved_by": "pat", "at": "t", "request_sha256": d}
    assert same_request(stamp, actor="pat", digest=d, actor_key="approved_by")
    assert not same_request(stamp, actor="pat", digest="0" * 64,
                            actor_key="approved_by")
