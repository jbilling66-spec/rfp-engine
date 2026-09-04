"""The access-log line's closed vocabularies (P26b-2 schema commit for
P2-46): the restricted store's L0 read doors log with actions of their
own, and the machine's lineage reads while ingesting carry a purpose the
grants table can name. A vocabulary any caller can widen is a comment,
not a control (S8) — so the enums are pinned here."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "access-log.schema.json"
GRANTS = ROOT / "config" / "kb-access.yaml"


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_action_vocabulary_names_the_source_doors():
    actions = _schema()["properties"]["action"]["enum"]
    assert actions == ["read", "scan_index", "reverse_index", "delete",
                       "sweep", "source_read", "list_sources",
                       "absorbed_lookup"]


def test_purpose_vocabulary_carries_ingest_and_the_grants_agree():
    purposes = _schema()["properties"]["purpose"]["enum"]
    assert purposes == ["audit", "purge", "right_of_review",
                        "anonymization_scan", "ingest"]
    grants = yaml.safe_load(GRANTS.read_text(encoding="utf-8"))["actors"]
    assert set(grants["engine"]) == {"anonymization_scan", "purge", "ingest"}
    for actor, granted in grants.items():
        assert set(granted) <= set(purposes), actor
    # The human-only purposes stay human-only.
    assert "audit" not in grants["engine"]
    assert "right_of_review" not in grants["engine"]


def test_doc_id_is_an_optional_field_and_the_line_stays_closed():
    schema = _schema()
    assert schema["additionalProperties"] is False
    assert "doc_id" in schema["properties"]
    assert "doc_id" not in schema["required"]
