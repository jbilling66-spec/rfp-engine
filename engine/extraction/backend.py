"""Extraction backend seam (C9) — how production reaches docling (B57).

One worker, two constructions, resolved in order:

1. InContainerBackend — docling is importable (the gate image / the A5
   runtime, where the engine itself lives in the container). Verify the
   vendored weights, then convert in the C2 jail. This is the literal A5
   shape; everything below it is dev-machine transport.
2. DockerBackend — docling absent but Docker + the gate image are present
   (the owner's machine pre-A5): the same worker invoked inside the image via
   `docker run --rm --network none`. Dev-machine-only by decision (B53:
   production never touches Docker Desktop — Azure consumes the image).
3. Neither → ExtractionUnavailable. The owner's call (2026-08-23, B58): intake
   REFUSES loudly rather than quietly un-adopting docling; the explicit
   RFP_EXTRACTION_FALLBACK=1 override runs legacy extractors with every
   pdf/docx document stamped degraded + flagged.

Both constructions verify weights against the committed manifest BEFORE any
docling import (B51's construction-refusal pattern; weights.py names this
module as its consumer). Per-document failure is ExtractionFailed — the
intake adapter degrades that one document; it is not an environment refusal.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from engine.extraction.model import ExtractionView
from engine.extraction.weights import verify_artifacts
from engine.extraction.worker import (
    PRODUCTION_TIMEOUT_S,
    run_production_conversion,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

GATE_IMAGE = "rfp-extraction-gate"

# The env var name is part of the recorded call (B58) — tests pin it.
FALLBACK_ENV = "RFP_EXTRACTION_FALLBACK"


class ExtractionUnavailable(RuntimeError):
    """Environment-level: no way to run docling here. Intake refuses."""


class ExtractionFailed(RuntimeError):
    """Document-level: this conversion failed. The adapter degrades it."""


def _docling_importable() -> bool:
    return importlib.util.find_spec("docling") is not None


def _docker_ready(image: str = GATE_IMAGE) -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    probe = subprocess.run(
        [docker, "image", "inspect", image], capture_output=True, text=True
    )
    return probe.returncode == 0


class InContainerBackend:
    identity = "docling"

    def __init__(self):
        verify_artifacts()  # refuse before docling is ever imported (B51)

    def convert(self, path: Path, mode: str = "deterministic") -> ExtractionView:
        with tempfile.TemporaryDirectory(prefix="extract-") as td:
            res = run_production_conversion(Path(path), mode, Path(td))
        if res.status != "ok":
            raise ExtractionFailed(f"{path}: {res.status}: {res.error}")
        return _view_or_fail(path, res.result)  # P1-29: the same guard


def _view_or_fail(path: Path, view) -> ExtractionView:
    """P1-29: a view the model rejects is a DOCUMENT failure, typed."""
    if not isinstance(view, dict):
        raise ExtractionFailed(
            f"{path}: worker result carries no view ({type(view).__name__})")
    try:
        return ExtractionView.from_dict(view)
    except (KeyError, TypeError, ValueError) as exc:
        raise ExtractionFailed(
            f"{path}: worker view malformed ({type(exc).__name__}: {exc})"
        ) from exc


class DockerBackend:
    identity = "docling"

    def __init__(self, image: str = GATE_IMAGE):
        verify_artifacts()  # host-side models/ is what gets mounted
        self.image = image

    def command(self, path: Path, mode: str) -> list[str]:
        """The pinned invocation: network disabled, repo read-only at
        /work (weights + code), document dir read-only at /data."""
        doc = Path(path).resolve()
        return [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{_REPO_ROOT}:/work:ro",
            "-v", f"{doc.parent}:/data:ro",
            "-w", "/work", self.image,
            "python", "-m", "engine.extraction.worker",
            f"/data/{doc.name}", mode,
        ]

    def convert(self, path: Path, mode: str = "deterministic") -> ExtractionView:
        # P1-29 (P26b-1, B112): every way the worker's result can be
        # malformed — a timeout, empty stdout, a non-JSON last line, a
        # result without `view`, a view the model rejects — is
        # ExtractionFailed, the ONE type the intake lane degrades on;
        # anything else escaped and killed the whole intake job.
        try:
            proc = subprocess.run(
                self.command(path, mode),
                capture_output=True, text=True,
                timeout=PRODUCTION_TIMEOUT_S + 120,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractionFailed(
                f"{path}: worker timed out after {exc.timeout}s") from exc
        if proc.returncode != 0 and not proc.stdout.strip():
            raise ExtractionFailed(
                f"{path}: container run failed: {proc.stderr.strip()[-600:]}"
            )
        try:
            out = json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:  # JSONDecodeError is a ValueError
            raise ExtractionFailed(
                f"{path}: worker result malformed ({type(exc).__name__}; "
                f"exit {proc.returncode}): stdout tail "
                f"{proc.stdout.strip()[-200:]!r}; stderr "
                f"{proc.stderr.strip()[-300:]}") from exc
        if not isinstance(out, dict) or out.get("status") != "ok":
            status = out.get("status") if isinstance(out, dict) else type(out).__name__
            error = out.get("error") if isinstance(out, dict) else out
            raise ExtractionFailed(f"{path}: {status}: {error}")
        return _view_or_fail(path, out.get("view"))


def resolve_backend(image: str = GATE_IMAGE):
    if _docling_importable():
        return InContainerBackend()
    if _docker_ready(image):
        return DockerBackend(image)
    raise ExtractionUnavailable(
        "docling extraction backend unavailable: docling is not importable "
        f"here and the {image} image is not runnable. Fix: start Docker "
        "Desktop and run `make gate-image` (the image is recipe-only by "
        f"decision, B55). Explicit override: {FALLBACK_ENV}=1 runs the "
        "legacy extractors with every pdf/docx document stamped degraded "
        "and flagged for review."
    )
