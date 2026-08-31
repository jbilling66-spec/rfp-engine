"""kb_snapshot (O4): the KB version string that makes two runs comparable.

Digest over cards/ only — restricted content cannot influence a run, so it
is deliberately outside the snapshot.
"""

from engine.kb import KBStore, snapshot_id

PROV = {"source_pursuit": "pur_x", "source_client": "Meridian Health Partners",
        "date": "2025-11-14", "ingested_by": "ingestion_agent"}


def _card(kb_id):
    return {"kb_id": kb_id, "layer": "corpus", "summary": "A [CLIENT] story."}


def test_empty_store_is_kb_at_empty(tmp_path):
    assert snapshot_id(tmp_path / "kb") == "kb@empty"
    KBStore(tmp_path / "kb")  # mkdirs alone don't change it
    assert snapshot_id(tmp_path / "kb") == "kb@empty"


def test_snapshot_changes_with_content(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(_card("kb_aa00000000"), "Body one.", PROV, {})
    first = store.snapshot()
    assert first.startswith("kb@") and first != "kb@empty"
    store.write_card(_card("kb_bb00000000"), "Body two.", PROV, {})
    assert store.snapshot() != first


def test_snapshot_reproducible_across_directories(tmp_path):
    for name in ("one", "two"):
        store = KBStore(tmp_path / name)
        store.write_card(_card("kb_aa00000000"), "Body one.", PROV, {})
    assert snapshot_id(tmp_path / "one") == snapshot_id(tmp_path / "two")


def test_restricted_content_outside_snapshot(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.write_card(_card("kb_aa00000000"), "Body one.", PROV, {"A": "CLIENT"})
    before = store.snapshot()
    store.restricted.append_source(
        "kb_aa00000000",
        {"source_pursuit": "pur_y", "source_client": "Cascade Valley Medical Center",
         "date": "2026-02-01"},
        {"B": "CLIENT"},
    )
    assert store.snapshot() == before
