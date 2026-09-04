"""The restricted provenance boundary (S8): log first, then authorize.

WP1's clause the ROADMAP row dropped but SESSION.md kept: "provenance
restricted and enforced by an authorization check with its own access log."
A restricted field any query can return is a comment, not a control.
"""

import json

import pytest

from engine.kb import KBStore, ProvenanceAccessDenied, RestrictedStore

PROV = {
    "source_pursuit": "pur_meridian_2025",
    "source_client": "Meridian Health Partners",
    "date": "2025-11-14",
    "ingested_by": "ingestion_agent",
}

IDENTIFIERS = {
    "Meridian Health Partners": "CLIENT",
    "$1,975,000": "FEE",
    "Dana Whitfield": "REFERENCE_NAME",
}


def _store(tmp_path) -> RestrictedStore:
    rs = RestrictedStore(tmp_path / "kb")
    rs.write("kb_ab12cd34ef", PROV, IDENTIFIERS)
    return rs


def _log_lines(rs: RestrictedStore) -> list[dict]:
    return [
        json.loads(line)
        for line in rs.access_log.read_text(encoding="utf-8").splitlines()
    ]


def test_provenance_absent_from_card_files(tmp_path):
    store = KBStore(tmp_path / "kb")
    card = {
        "kb_id": "kb_ab12cd34ef", "layer": "corpus",
        "summary": "A [CLIENT] cutover story.",
    }
    store.write_card(card, "Body for [CLIENT].", PROV, IDENTIFIERS)
    text = (tmp_path / "kb" / "cards" / "kb_ab12cd34ef.md").read_text()
    assert "provenance" not in text
    assert "Meridian" not in text
    assert "pur_meridian_2025" not in text


def test_read_requires_authorization(tmp_path):
    rs = _store(tmp_path)
    with pytest.raises(ProvenanceAccessDenied):
        rs.read("kb_ab12cd34ef", actor="engine", purpose="audit")
    with pytest.raises(ProvenanceAccessDenied):
        rs.read("kb_ab12cd34ef", actor="mallory", purpose="audit")


def test_denied_read_is_access_logged(tmp_path):
    rs = _store(tmp_path)
    with pytest.raises(ProvenanceAccessDenied):
        rs.read("kb_ab12cd34ef", actor="mallory", purpose="audit")
    line = _log_lines(rs)[-1]
    assert line["actor"] == "mallory"
    assert line["purpose"] == "audit"
    assert line["granted"] is False
    assert line["kb_id"] == "kb_ab12cd34ef"


def test_authorized_read_returns_full_record_and_logs(tmp_path):
    rs = _store(tmp_path)
    record = rs.read("kb_ab12cd34ef", actor="owner", purpose="audit")
    assert record["sources"] == [
        {"source_pursuit": "pur_meridian_2025",
         "source_client": "Meridian Health Partners", "date": "2025-11-14"}
    ]
    assert record["identifiers"] == IDENTIFIERS
    line = _log_lines(rs)[-1]
    assert (line["actor"], line["granted"]) == ("owner", True)


def test_access_log_is_its_own_file_not_run_log_lines(tmp_path):
    rs = _store(tmp_path)
    rs.read("kb_ab12cd34ef", actor="owner", purpose="audit")
    assert rs.access_log == tmp_path / "kb" / "restricted" / "access.jsonl"
    for line in _log_lines(rs):
        assert "seq" not in line and "run_id" not in line


def test_reverse_index_answers_where_is_my_name_used(tmp_path):
    rs = _store(tmp_path)
    hits = rs.reverse_index("Dana Whitfield", actor="owner")
    assert hits == [{"kb_id": "kb_ab12cd34ef", "placeholder": "REFERENCE_NAME"}]
    by_client = rs.reverse_index("meridian health", actor="owner")
    assert {"kb_id": "kb_ab12cd34ef", "placeholder": "CLIENT"} in by_client
    assert _log_lines(rs)[-1]["purpose"] == "right_of_review"


def test_reverse_index_requires_authorization(tmp_path):
    rs = _store(tmp_path)
    with pytest.raises(ProvenanceAccessDenied):
        rs.reverse_index("Dana Whitfield", actor="engine")


def test_append_source_merges_for_purge_safety(tmp_path):
    rs = _store(tmp_path)
    second = {"source_pursuit": "pur_cascade_2026",
              "source_client": "Cascade Valley Medical Center",
              "date": "2026-02-01", "ingested_by": "ingestion_agent"}
    rs.append_source("kb_ab12cd34ef", second,
                     {"Cascade Valley Medical Center": "CLIENT"})
    record = rs.read("kb_ab12cd34ef", actor="owner", purpose="audit")
    assert len(record["sources"]) == 2
    assert "Cascade Valley Medical Center" in record["identifiers"]


def test_scan_index_is_machine_readable_and_logged(tmp_path):
    rs = _store(tmp_path)
    index = rs.scan_index()
    assert index == {"kb_ab12cd34ef": sorted(IDENTIFIERS)}
    line = _log_lines(rs)[-1]
    assert (line["actor"], line["action"]) == ("engine", "scan_index")


def test_delete_requires_purge_authorization_and_logs(tmp_path):
    rs = _store(tmp_path)
    with pytest.raises(ProvenanceAccessDenied):
        rs.delete("kb_ab12cd34ef", actor="mallory")
    rs.delete("kb_ab12cd34ef", actor="engine")
    assert not (rs.prov_dir / "kb_ab12cd34ef.json").exists()
    assert _log_lines(rs)[-1]["action"] == "delete"


def test_access_log_lines_validate_and_the_guard_fires(tmp_path):
    """E4 (B37/D23): every line the real paths write is schema-valid, and
    the write-site guard is non-vacuous — an off-vocabulary purpose raises
    instead of appending a line the vocabulary control never covered."""
    from engine.contracts import ContractError, validate

    rs = _store(tmp_path)
    rs.read("kb_ab12cd34ef", actor="owner", purpose="audit")
    with pytest.raises(ProvenanceAccessDenied):
        rs.read("kb_ab12cd34ef", actor="mallory", purpose="audit")
    rs.log_sweep(actor="owner", client="Meridian Health Partners", clean=True)
    lines = _log_lines(rs)
    assert len(lines) >= 3  # granted + denied + sweep: non-vacuous corpus
    for line in lines:
        validate("access_log", line)
    with pytest.raises(ContractError):
        rs._log("owner", "not_a_purpose", "read", True)
    assert len(_log_lines(rs)) == len(lines)  # the rejected line never landed


# ---------------------------------------------- P2-46: the L0 read doors

def test_source_doors_log_and_authorize(tmp_path):
    """P2-46 (P26b-2): existence, meta, the listing and the merge-fold
    lookup answer to the same law as `read` — a line first, then the
    decision. Before this the four answered silently, and the meta
    carries the real source_client."""
    rs = _store(tmp_path)
    rs.write_source("cd_0123456789ab", b"raw client bytes",
                    {"doc_id": "tw_doc", "source_client": "Meridian"})
    for call in (
        lambda a: rs.source_exists("cd_0123456789ab", actor=a, purpose="audit"),
        lambda a: rs.source_meta("cd_0123456789ab", actor=a, purpose="audit"),
        lambda a: rs.source_metas(actor=a, purpose="audit"),
        lambda a: rs.list_source_ids(actor=a, purpose="audit"),
        lambda a: rs.absorbed_owners(actor=a, purpose="audit"),
    ):
        with pytest.raises(ProvenanceAccessDenied):
            call("mallory")
        denied = _log_lines(rs)[-1]
        assert denied["actor"] == "mallory" and denied["granted"] is False
        call("owner")
        granted = _log_lines(rs)[-1]
        assert granted["actor"] == "owner" and granted["granted"] is True
    actions = [line["action"] for line in _log_lines(rs)[-10:]]
    assert actions == ["source_read", "source_read", "source_read",
                       "source_read", "source_read", "source_read",
                       "list_sources", "list_sources",
                       "absorbed_lookup", "absorbed_lookup"]
    meta_lines = [line for line in _log_lines(rs)
                  if line.get("doc_id") == "cd_0123456789ab"]
    assert len(meta_lines) == 4, "existence and meta reads name the artifact"
    assert rs.source_meta("cd_0123456789ab", actor="owner",
                          purpose="audit")["source_client"] == "Meridian"
    # The engine's lineage reads carry their own purpose — granted to the
    # machine identity, and only that.
    assert rs.source_exists("cd_0123456789ab", actor="engine",
                            purpose="ingest") is True
    with pytest.raises(ProvenanceAccessDenied):
        rs.source_meta("cd_0123456789ab", actor="engine", purpose="audit")


def test_prior_models_goes_through_the_door(tmp_path):
    """reconcile.prior_models used to read the source dir directly."""
    from engine.kb import KBStore
    from engine.kb.reconcile import prior_models

    store = KBStore(tmp_path / "kb")
    store.restricted.write_source("cd_aaaaaaaaaaaa", b"v1", {"doc_id": "d"})
    store.restricted.write_source("cd_bbbbbbbbbbbb", b"v2", {"doc_id": "d"})
    store.restricted.write_source("cd_cccccccccccc", b"x", {"doc_id": "other"})
    with pytest.raises(ProvenanceAccessDenied):
        prior_models(store, "d", "cd_bbbbbbbbbbbb", actor="mallory",
                     purpose="ingest")
    assert prior_models(store, "d", "cd_bbbbbbbbbbbb", actor="engine",
                        purpose="ingest") == ["cd_aaaaaaaaaaaa"]
    lines = _log_lines(store.restricted)
    assert [l["action"] for l in lines[-2:]] == ["source_read", "source_read"]
    assert [l["granted"] for l in lines[-2:]] == [False, True]
