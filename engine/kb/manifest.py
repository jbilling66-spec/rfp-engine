"""Core-content manifest: the service line's must-have content inventory.

The formal contract is schemas/manifest.schema.json (B27, closing B16's
deferral now that P6 consumes obligations onto the pursuit plan). This
loader delegates shape checks to it and keeps the one rule jsonschema
cannot express: obligation ids are unique.

    service_line: erp-implementation
    obligations:
      - {id: pm-approach, title: Project management approach}
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.contracts import ContractError, validate


class ManifestError(ValueError):
    """A manifest violated its contract (named file, named reason)."""


@dataclass
class Manifest:
    service_line: str
    obligations: list[dict]

    def obligation_ids(self) -> list[str]:
        return [o["id"] for o in self.obligations]


def load_manifest(path: Path) -> Manifest:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestError(f"{path.name}: manifest must be a mapping")
    try:
        validate("manifest", raw)
    except ContractError as e:
        raise ManifestError(f"{path.name}: {e}") from e
    seen = set()
    for obligation in raw["obligations"]:
        oid = obligation["id"]
        if oid in seen:
            raise ManifestError(f"{path.name}: duplicate obligation id {oid!r}")
        seen.add(oid)
    return Manifest(service_line=raw["service_line"], obligations=raw["obligations"])
