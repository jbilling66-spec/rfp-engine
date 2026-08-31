"""Vendored-weights refusal proofs (C3, B51) — offline, fake tree.

The real manifest is committed only after the first real download
(make extraction-models); these tests prove the machinery refuses
everything it must refuse, against a tmp_path tree — including the
canonical can-fail: one corrupted byte fires the guard.
"""

from __future__ import annotations

import json

import pytest

from engine.extraction.weights import WeightsError, freeze, verify_artifacts


def _fake_tree(root):
    (root / "docling" / "layout").mkdir(parents=True)
    (root / "docling" / "layout" / "model.bin").write_bytes(b"layout-weights-bytes")
    (root / "docling" / "tableformer.bin").write_bytes(b"tableformer-weights")
    return root


def test_freeze_then_verify_round_trips(tmp_path):
    root = _fake_tree(tmp_path / "models")
    mf = tmp_path / "extraction-models.json"
    manifest = freeze(root, mf, docling_version="test-0")
    assert set(manifest["models"]) == {"docling/layout/model.bin", "docling/tableformer.bin"}
    assert manifest["docling_version"] == "test-0"
    assert all(e["bytes"] > 0 and len(e["sha256"]) == 64 for e in manifest["models"].values())
    verified = verify_artifacts(root, mf)
    assert verified["models"] == manifest["models"]


def test_verify_refuses_missing_manifest(tmp_path):
    root = _fake_tree(tmp_path / "models")
    with pytest.raises(WeightsError, match="no weights manifest"):
        verify_artifacts(root, tmp_path / "never-written.json")


def test_verify_refuses_empty_manifest(tmp_path):
    root = _fake_tree(tmp_path / "models")
    mf = tmp_path / "extraction-models.json"
    mf.write_text(json.dumps({"docling_version": "test-0", "models": {}}))
    with pytest.raises(WeightsError, match="records no files"):
        verify_artifacts(root, mf)


def test_verify_refuses_missing_file(tmp_path):
    root = _fake_tree(tmp_path / "models")
    mf = tmp_path / "extraction-models.json"
    freeze(root, mf, docling_version="test-0")
    (root / "docling" / "tableformer.bin").unlink()
    with pytest.raises(WeightsError, match="missing from tree.*tableformer"):
        verify_artifacts(root, mf)


def test_verify_refuses_one_corrupted_byte(tmp_path):
    """The canonical can-fail: same size, one byte flipped, guard fires."""
    root = _fake_tree(tmp_path / "models")
    mf = tmp_path / "extraction-models.json"
    freeze(root, mf, docling_version="test-0")
    target = root / "docling" / "layout" / "model.bin"
    corrupted = bytearray(target.read_bytes())
    corrupted[0] ^= 0xFF
    target.write_bytes(bytes(corrupted))
    with pytest.raises(WeightsError, match="digest mismatch.*model.bin"):
        verify_artifacts(root, mf)


def test_verify_refuses_unrecorded_file(tmp_path):
    root = _fake_tree(tmp_path / "models")
    mf = tmp_path / "extraction-models.json"
    freeze(root, mf, docling_version="test-0")
    (root / "docling" / "smuggled.bin").write_bytes(b"not in the manifest")
    with pytest.raises(WeightsError, match="unrecorded files.*smuggled"):
        verify_artifacts(root, mf)


def test_dot_entries_are_neither_recorded_nor_held_against_the_tree(tmp_path):
    root = _fake_tree(tmp_path / "models")
    (root / ".DS_Store").write_bytes(b"finder noise")
    (root / "docling" / ".locks").mkdir()
    (root / "docling" / ".locks" / "x.lock").write_bytes(b"hub lockfile")
    mf = tmp_path / "extraction-models.json"
    manifest = freeze(root, mf, docling_version="test-0")
    assert all(not p.split("/")[-1].startswith(".") for p in manifest["models"])
    verify_artifacts(root, mf)  # extras that are dot-entries do not refuse


def test_freeze_refuses_an_empty_tree(tmp_path):
    with pytest.raises(WeightsError, match="nothing to freeze"):
        freeze(tmp_path / "models", tmp_path / "mf.json", docling_version="test-0")
