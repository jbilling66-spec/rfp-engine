"""C9: the backend seam — resolution order, loud refusal, verify-before-
docling ordering, and the pinned docker invocation. All offline: docling is
absent here by the dependency seam, which is exactly the condition these
tests exercise."""

import pytest

from engine.extraction import backend as backend_mod
from engine.extraction.backend import (
    FALLBACK_ENV,
    DockerBackend,
    ExtractionUnavailable,
    InContainerBackend,
    resolve_backend,
)
from engine.extraction.weights import WeightsError


def test_resolution_prefers_in_container(monkeypatch):
    monkeypatch.setattr(backend_mod, "_docling_importable", lambda: True)
    monkeypatch.setattr(backend_mod, "verify_artifacts", lambda: {})
    assert isinstance(resolve_backend(), InContainerBackend)


def test_resolution_falls_to_docker_transport(monkeypatch):
    monkeypatch.setattr(backend_mod, "_docling_importable", lambda: False)
    monkeypatch.setattr(backend_mod, "_docker_ready", lambda image: True)
    monkeypatch.setattr(backend_mod, "verify_artifacts", lambda: {})
    assert isinstance(resolve_backend(), DockerBackend)


def test_neither_refuses_loudly_naming_the_fixes(monkeypatch):
    monkeypatch.setattr(backend_mod, "_docling_importable", lambda: False)
    monkeypatch.setattr(backend_mod, "_docker_ready", lambda image: False)
    with pytest.raises(ExtractionUnavailable) as exc:
        resolve_backend()
    message = str(exc.value)
    # The refusal must name the repair and the recorded override — a
    # misconfigured machine gets instructions, never a silent downgrade.
    assert "make gate-image" in message
    assert "Docker Desktop" in message
    assert FALLBACK_ENV in message
    assert "degraded" in message


def test_construction_verifies_weights_before_anything_runs(monkeypatch):
    def refuse():
        raise WeightsError("digest mismatch: models/docling/x.bin")

    ran = []
    monkeypatch.setattr(backend_mod, "verify_artifacts", refuse)
    monkeypatch.setattr(
        backend_mod, "run_production_conversion",
        lambda *a, **k: ran.append(a) or None,
    )
    with pytest.raises(WeightsError):
        InContainerBackend()
    with pytest.raises(WeightsError):
        DockerBackend()
    assert ran == []  # refusal happened at construction, nothing converted


def test_docker_command_pinned(monkeypatch, tmp_path):
    # The invocation IS the containment: --network none and read-only
    # mounts are load-bearing, so the exact argv is pinned.
    monkeypatch.setattr(backend_mod, "verify_artifacts", lambda: {})
    doc = tmp_path / "rfp.pdf"
    doc.write_bytes(b"%PDF-")
    cmd = DockerBackend().command(doc, "deterministic")
    repo = backend_mod._REPO_ROOT
    assert cmd == [
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{repo}:/work:ro",
        "-v", f"{doc.parent.resolve()}:/data:ro",
        "-w", "/work", "rfp-extraction-gate",
        "python", "-m", "engine.extraction.worker",
        f"/data/{doc.name}", "deterministic",
    ]


def test_fake_backend_scripts_views_and_failures(tmp_path):
    from engine.extraction.backend import ExtractionFailed
    from tests.extraction.fakes import FakeExtractionBackend, simple_view

    fake = FakeExtractionBackend({
        "a.pdf": simple_view("hello", pages=2),
        "a.pdf:vlm": simple_view("hello-vlm", pages=2),
        "bad.pdf": ExtractionFailed("bad.pdf: conversion failure"),
    })
    view = fake.convert(tmp_path / "a.pdf")
    assert view.text == "hello" and view.pages == 2
    assert fake.convert(tmp_path / "a.pdf", mode="vlm").text == "hello-vlm"
    with pytest.raises(ExtractionFailed):
        fake.convert(tmp_path / "bad.pdf")
    assert fake.calls == [("a.pdf", "deterministic"), ("a.pdf", "vlm"),
                          ("bad.pdf", "deterministic")]
