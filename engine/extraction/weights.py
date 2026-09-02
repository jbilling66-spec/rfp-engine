"""Vendored-weights manifest and verifier (C3, B51).

Docling fetches models from a public hub by default; production never
does (spec §A3 — live law since B44). The weights tree lives in
gitignored `models/` (override: $RFP_EXTRACTION_MODELS); the committed
record is `config/extraction-models.json` — sha256 + size for every
file, plus the docling version that downloaded them. verify_artifacts()
re-hashes the tree and refuses on any divergence; the backend (C9)
calls it before importing docling — the RFP_LIVE construction-refusal
pattern applied to the supply chain.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import write_json_atomic

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHUNK = 1024 * 1024


class WeightsError(Exception):
    """A refusal: the weights tree cannot be proven to be the vendored one."""


def models_root() -> Path:
    import os

    override = os.environ.get("RFP_EXTRACTION_MODELS")
    return Path(override) if override else _REPO_ROOT / "models"


def manifest_path() -> Path:
    return _REPO_ROOT / "config" / "extraction-models.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_files(root: Path) -> list[Path]:
    # Dot-entries (hub lockfiles, .DS_Store) are neither recorded nor
    # held against the tree; everything else is.
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def freeze(
    root: Path | None = None,
    manifest_file: Path | None = None,
    docling_version: str | None = None,
) -> dict:
    root = root or models_root()
    manifest_file = manifest_file or manifest_path()
    files = _tree_files(root) if root.is_dir() else []
    if not files:
        raise WeightsError(
            f"nothing to freeze under {root} — an empty manifest would verify "
            "an empty tree; download weights first (make extraction-models)"
        )
    if docling_version is None:
        from importlib import metadata

        try:
            docling_version = metadata.version("docling")
        except metadata.PackageNotFoundError as exc:
            raise WeightsError(
                "docling is not installed here — freeze runs inside the gate "
                "container (make extraction-models)"
            ) from exc
    manifest = {
        "docling_version": docling_version,
        "downloaded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": {
            str(p.relative_to(root)): {"sha256": _sha256(p), "bytes": p.stat().st_size}
            for p in files
        },
    }
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(manifest_file, manifest)  # P0-6: the B55 continuity proof
    return manifest


def verify_artifacts(
    root: Path | None = None, manifest_file: Path | None = None
) -> dict:
    """Refuse unless the tree matches the committed manifest exactly."""
    root = root or models_root()
    manifest_file = manifest_file or manifest_path()
    if not manifest_file.is_file():
        raise WeightsError(
            f"no weights manifest at {manifest_file} — the vendored artifact "
            "record does not exist; run make extraction-models, then commit it"
        )
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    recorded: dict = manifest.get("models") or {}
    if not recorded:
        raise WeightsError(f"manifest {manifest_file} records no files")

    for relpath, entry in recorded.items():
        path = root / relpath
        if not path.is_file():
            raise WeightsError(f"vendored file missing from tree: {relpath}")
        if path.stat().st_size != entry["bytes"]:
            raise WeightsError(f"size mismatch (recorded {entry['bytes']}): {relpath}")
        if _sha256(path) != entry["sha256"]:
            raise WeightsError(f"digest mismatch against the manifest: {relpath}")

    extras = [
        str(p.relative_to(root)) for p in _tree_files(root)
        if str(p.relative_to(root)) not in recorded
    ]
    if extras:
        raise WeightsError(
            f"unrecorded files in the weights tree (supply-chain smell): {extras[:5]}"
        )
    return manifest


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("freeze", "verify"):
        print("usage: python -m engine.extraction.weights {freeze|verify}")
        return 2
    try:
        if argv[0] == "freeze":
            manifest = freeze()
            print(f"froze {len(manifest['models'])} files -> {manifest_path()}")
        else:
            manifest = verify_artifacts()
            print(
                f"verified {len(manifest['models'])} files against "
                f"{manifest_path()} (docling {manifest['docling_version']})"
            )
    except WeightsError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
