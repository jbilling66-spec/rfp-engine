"""P2-59 (P29b b6): a retained `.src` with no meta — the `write_source`
crash window — was invisible to `source_metas`, so the client's raw
un-anonymized bytes survived `purge_client` and the report said CLEAN.
The owner's call (B130 §1c): an orphan has no client, no card and no
lineage, so it is REMOVED on every purge and named in the accounting;
`write_source` writes the meta first so a future crash leaves the
harmless shape."""

import json

import pytest

from engine.kb import KBStore, purge_client
from engine.kb import provenance as provenance_mod

ORPHAN = "cd_0123456789ab"


def _access_actions(store):
    return [json.loads(l)["action"] for l in
            store.restricted.access_log.read_text().splitlines()]


def test_an_orphan_source_is_removed_and_named_by_any_purge(tmp_path):
    store = KBStore(tmp_path / "kb")
    restricted = store.restricted
    src_dir = restricted._source_dir()
    src_dir.mkdir(parents=True, exist_ok=True)
    orphan = src_dir / f"{ORPHAN}.src"
    orphan.write_bytes(b"raw client text that no meta attributes")
    assert restricted.list_source_ids(actor="owner", purpose="audit") == [ORPHAN]
    assert restricted.source_metas(actor="owner", purpose="audit") == {}
    assert restricted.orphan_source_ids(actor="owner", purpose="audit") == [ORPHAN]
    purge = purge_client(store, "Nobody In Particular", actor="owner")
    assert purge.accounting["l0_orphans_removed"] == [ORPHAN]
    assert purge.accounting["l0_sources"] == []  # not attributable, named apart
    assert not orphan.exists()
    assert restricted.list_source_ids(actor="owner", purpose="audit") == []
    assert purge.swept_clean
    actions = _access_actions(store)
    assert "list_sources" in actions and "source_read" in actions


def test_a_control_source_with_its_meta_is_untouched_by_the_orphan_walk(
        tmp_path):
    store = KBStore(tmp_path / "kb")
    restricted = store.restricted
    restricted.write_source("cd_ba9876543210", b"attributed bytes",
                            {"doc_id": "cd_ba9876543210",
                             "source_client": "Someone Else"})
    assert restricted.orphan_source_ids(actor="owner", purpose="audit") == []
    purge = purge_client(store, "Nobody In Particular", actor="owner")
    assert purge.accounting["l0_orphans_removed"] == []
    assert restricted.source_exists("cd_ba9876543210", actor="owner",
                                    purpose="audit")


def test_write_source_writes_the_meta_before_the_bytes(tmp_path, monkeypatch):
    store = KBStore(tmp_path / "kb")
    restricted = store.restricted

    def boom(path, data):
        raise OSError("crash between the two writes")

    monkeypatch.setattr(provenance_mod, "write_bytes_atomic", boom)
    with pytest.raises(OSError, match="between the two writes"):
        restricted.write_source("cd_c0ffee000001", b"never lands",
                                {"doc_id": "cd_c0ffee000001",
                                 "source_client": "Crashed Corp"})
    src_dir = restricted._source_dir()
    assert (src_dir / "cd_c0ffee000001.json").exists()  # the harmless shape
    assert not (src_dir / "cd_c0ffee000001.src").exists()
    assert restricted.list_source_ids(actor="owner", purpose="audit") == []
    assert restricted.orphan_source_ids(actor="owner", purpose="audit") == []
    restricted.delete_source("cd_c0ffee000001")  # tolerated (missing_ok)
    assert not (src_dir / "cd_c0ffee000001.json").exists()
