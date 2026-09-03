"""P1-29 (P26b-1, B112): every malformed worker result is ExtractionFailed —
the one type the intake lane degrades a single document on — never the
raw IndexError / JSONDecodeError / KeyError / ValueError / TimeoutExpired
that used to escape `convert` and kill the whole intake job. The docker
transport is faked at `subprocess.run`; the in-container path at
`run_production_conversion`."""

import subprocess
from types import SimpleNamespace

import pytest

from engine.extraction import backend as backend_mod
from engine.extraction.backend import (
    DockerBackend, ExtractionFailed, InContainerBackend,
)


@pytest.fixture
def docker(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_mod, "verify_artifacts", lambda: {})
    doc = tmp_path / "rfp.pdf"
    doc.write_bytes(b"%PDF-")
    return DockerBackend(), doc


def _completed(stdout, returncode=0, stderr=""):
    return lambda *a, **k: subprocess.CompletedProcess(
        a[0], returncode, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize("stdout, returncode, names", [
    ("", 0, ("malformed", "IndexError")),            # empty stdout, clean exit
    ("progress line\nnot json", 0, ("malformed", "JSONDecodeError")),
    ('{"status": "ok"}', 0, ("no view",)),           # missing `view`
    ('{"status": "ok", "view": 7}', 0, ("no view", "int")),
    ('{"status": "ok", "view": {"bogus": 1}}', 0, ("view malformed",)),
    ('{"status": "error", "error": "docling choked"}', 1, ("error", "docling choked")),
    ('[1, 2]', 0, ("list",)),                        # JSON, wrong shape
], ids=["empty", "non-json", "no-view", "view-not-dict", "view-rejected",
        "worker-error-nonzero-exit", "wrong-shape"])
def test_every_malformation_is_extraction_failed(monkeypatch, docker,
                                                  stdout, returncode, names):
    backend, doc = docker
    monkeypatch.setattr(backend_mod.subprocess, "run",
                        _completed(stdout, returncode, stderr="trace"))
    with pytest.raises(ExtractionFailed) as info:
        backend.convert(doc)
    for name in names:
        assert name in str(info.value)


def test_timeout_is_extraction_failed(monkeypatch, docker):
    backend, doc = docker

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout", 0))
    monkeypatch.setattr(backend_mod.subprocess, "run", boom)
    with pytest.raises(ExtractionFailed) as info:
        backend.convert(doc)
    assert "timed out" in str(info.value)


def test_in_container_rejects_a_bad_view_typed(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_mod, "verify_artifacts", lambda: {})
    monkeypatch.setattr(
        backend_mod, "run_production_conversion",
        lambda path, mode, td: SimpleNamespace(status="ok", error=None,
                                              result={"bogus": 1}))
    with pytest.raises(ExtractionFailed) as info:
        InContainerBackend().convert(tmp_path / "x.pdf")
    assert "view malformed" in str(info.value)


def test_a_well_formed_result_still_converts(monkeypatch, docker):
    import json

    from engine.extraction.model import ExtractionView
    from tests.extraction.fakes import simple_view
    backend, doc = docker
    view = simple_view()  # a minimal valid view dict
    payload = json.dumps({"status": "ok", "view": view})
    monkeypatch.setattr(backend_mod.subprocess, "run", _completed(payload))
    assert backend.convert(doc).to_dict() == ExtractionView.from_dict(view).to_dict()
