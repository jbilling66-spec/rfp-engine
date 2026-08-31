"""Extraction fingerprint (C12 lock, B51) — comparability for extraction
artifacts, and ONLY extraction artifacts.

The fingerprint stamps extraction outputs and cache keys so two artifacts
are comparable exactly when the stack that produced them is identical:
extractor identity, this layer's own version, the runtime docling version
(runtime, not the manifest's freeze value — the B56 dual-stamp lesson),
the weights-manifest digest (covers the frozen version and all 57 file
digests transitively), and the pipeline options.

It NEVER enters effective_config() or any existing fingerprint — the B50
eval baselines must not stale for a subsystem their measures never touched
(B51; pinned by tests/extraction/test_fingerprint.py). No component may
carry wall-clock time: intake artifacts are byte-identical across
kill/resume (brief.py).
"""

import hashlib
import json
from pathlib import Path

from engine.extraction import EXTRACTOR_VERSION
from engine.extraction.weights import manifest_path

# The single source for production pipeline options; the C9 worker consumes
# this constant so the fingerprint can never disagree with the conversion.
PIPELINE_OPTIONS = {
    "mode": "deterministic",
    "do_ocr": True,
    "do_table_structure": True,
    "do_picture_classification": True,
}


def stack_fingerprint(extractor: str, components: dict) -> str:
    """Fingerprint any extraction stack: sha256 over canonical JSON of the
    identity + components, rendered ext_<hex16>. The KB path (C12) stamps
    python-docx through this same function with its own components."""
    payload = {"extractor": extractor, **components}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "ext_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def manifest_digest(manifest_file: Path | None = None) -> str:
    """Digest of the committed weights manifest BYTES — a re-freeze, a
    version bump, or any single weight digest change all move it."""
    path = manifest_file or manifest_path()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extraction_fingerprint(
    docling_version: str,
    weights_manifest_sha256: str,
    pipeline_options: dict | None = None,
) -> str:
    """The docling-stack fingerprint (intake/Path-A, the B57 adoption)."""
    return stack_fingerprint(
        "docling",
        {
            "extractor_version": EXTRACTOR_VERSION,
            "docling_version": docling_version,
            "weights_manifest_sha256": weights_manifest_sha256,
            "pipeline_options": pipeline_options or PIPELINE_OPTIONS,
        },
    )
