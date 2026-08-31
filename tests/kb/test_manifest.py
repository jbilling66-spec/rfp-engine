"""The core-content manifest loads and validates (SESSION.md P2 action 5).

Since B27 the contract is schemas/manifest.schema.json; the loader
delegates to it and keeps the duplicate-id check. The tests pin every
rejection case as tightly as the acceptance — the match strings follow
the enforcement layer (jsonschema messages since B27).
"""

from pathlib import Path

import pytest

from engine.kb.manifest import ManifestError, load_manifest

ROOT = Path(__file__).resolve().parents[2]
ERP_MANIFEST = ROOT / "config" / "manifests" / "erp-implementation.yaml"


def test_erp_manifest_loads_and_validates():
    manifest = load_manifest(ERP_MANIFEST)
    assert manifest.service_line == "erp-implementation"
    assert len(manifest.obligations) >= 5
    ids = manifest.obligation_ids()
    assert len(ids) == len(set(ids))
    assert "training-ocm" in ids


def _write(tmp_path, text):
    path = tmp_path / "m.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("text,reason", [
    ("service_line: erp\nobligations: []\n", "non-empty"),
    ("service_line: erp\n", "required property"),
    ("service_line: erp\nobligations: [{id: a, title: T}]\nextra: 1\n",
     "'extra' was unexpected"),
    ("service_line: Erp Line\nobligations: [{id: a, title: T}]\n", "does not match"),
    ("service_line: erp\nobligations: [{id: 'Bad Id', title: T}]\n", "does not match"),
    ("service_line: erp\nobligations: [{id: a, title: T, owner: x}]\n",
     "'owner' was unexpected"),
    ("service_line: erp\nobligations: [{id: a, title: T}, {id: a, title: U}]\n",
     "duplicate"),
    ("service_line: erp\nobligations: [{id: a}]\n", "'title' is a required property"),
])
def test_malformed_manifest_rejected(tmp_path, text, reason):
    with pytest.raises(ManifestError, match=reason):
        load_manifest(_write(tmp_path, text))
