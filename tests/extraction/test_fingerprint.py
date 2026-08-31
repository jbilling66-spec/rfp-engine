"""C8: the extraction fingerprint is pinned by literal (the 30-pin culture),
moves with every component, carries no wall clock, and provably never enters
effective_config() — the B51 lock, test-carried."""

import json
from pathlib import Path

from engine.extraction.fingerprint import (
    PIPELINE_OPTIONS,
    extraction_fingerprint,
    manifest_digest,
    stack_fingerprint,
)
from engine.llm.config import effective_config

FIXED_MANIFEST_SHA = "a" * 64


def test_fingerprint_pinned_by_literal():
    # Recompute-and-compare would test nothing; the literal is the pin.
    # Moving it requires a deliberate edit here, which is the point.
    assert extraction_fingerprint("2.121.0", FIXED_MANIFEST_SHA) == (
        "ext_04954e307b957bf1"
    )


def test_every_component_moves_the_fingerprint():
    base = extraction_fingerprint("2.121.0", FIXED_MANIFEST_SHA)
    assert extraction_fingerprint("2.120.1", FIXED_MANIFEST_SHA) != base
    assert extraction_fingerprint("2.121.0", "b" * 64) != base
    perturbed = dict(PIPELINE_OPTIONS, do_ocr=False)
    assert extraction_fingerprint(
        "2.121.0", FIXED_MANIFEST_SHA, pipeline_options=perturbed
    ) != base


def test_no_wall_clock_component():
    a = extraction_fingerprint("2.121.0", FIXED_MANIFEST_SHA)
    b = extraction_fingerprint("2.121.0", FIXED_MANIFEST_SHA)
    assert a == b


def test_stack_fingerprints_are_extractor_distinct():
    # The C12 seam: same components under different identities never collide.
    components = {"extractor_version": "0.1.0"}
    assert stack_fingerprint("docling", components) != stack_fingerprint(
        "python-docx", components
    )


def test_manifest_digest_moves_with_bytes(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text('{"docling_version": "2.120.1"}')
    first = manifest_digest(m)
    m.write_text('{"docling_version": "2.121.0"}')
    assert manifest_digest(m) != first


def test_fingerprint_never_enters_effective_config():
    # Both halves of the B51 lock: the serialized config carries neither the
    # key nor any ext_ digest, and the config module cannot even reach the
    # extraction package (import-level separation, not just discipline).
    serialized = json.dumps(effective_config())
    assert "extraction_fingerprint" not in serialized
    assert '"ext_' not in serialized

    config_source = Path("engine/llm/config.py").read_text(encoding="utf-8")
    assert "engine.extraction" not in config_source
