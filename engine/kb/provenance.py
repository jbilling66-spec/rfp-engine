"""Restricted provenance store: the anti-leakage boundary (S3, S8, D1).

A card's provenance — who the client was, which pursuit, what identifiers
the placeholders replaced — is the de-anonymization key. S8: "a restricted
field any query can return is a comment, not a control." So this store has
exactly one read path, and it appends to its own access log BEFORE it
authorizes: every attempt, granted or denied, human or machine, leaves a
line. The log is a separate file from the run log by decision, not accident.

File shape (B14) is richer than the card schema's singular provenance
object: `sources` is a LIST so a merged card carries every contributing
{source_pursuit, source_client, date} and purging EITHER client removes it
(D1-safe conservative merge); `identifiers` maps each original string to
its placeholder type — the index the anonymization scan and the purge sweep
run against; `derived_from` is the D1 derivation link purge closure
traverses.

The access-log formal schema landed at P9/E4 (schemas/access-log.schema.json,
B30(c) closed): every line validates before it appends — a log the schema
rejects is a bug at the write site, never a malformed line to skip later.

Identity vs authorization (B14(3) closed, P10/c20). These were conflated
while config/kb-access.yaml was both — a name listed there was trusted as
given, so the log recorded a claim rather than a fact. They are now
separate: WHO comes from the authenticated operator (the web auth seam,
passed in as `actor` by every web-originated read), and WHAT THEY MAY DO
comes from the grants table below. An operator the table does not name is
denied and logged — fail closed, because the alternative is a curation
screen that quietly widens access to whoever is signed in. CLI callers
still pass their own actor; that path is a named operator at a terminal,
not an anonymous request.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from engine.contracts import write_bytes_atomic, write_json_atomic

import yaml

_DEFAULT_ACCESS_CONFIG = (
    Path(__file__).resolve().parents[2] / "config" / "kb-access.yaml"
)


class ProvenanceAccessDenied(PermissionError):
    """An actor tried to read restricted provenance without authorization."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RestrictedStore:
    def __init__(self, kb_root: Path, access_config: Path | None = None):
        self.root = Path(kb_root) / "restricted"
        self.prov_dir = self.root / "provenance"
        self.prov_dir.mkdir(parents=True, exist_ok=True)
        self.access_log = self.root / "access.jsonl"
        self._grants = self._load_grants(access_config or _DEFAULT_ACCESS_CONFIG)

    @staticmethod
    def _load_grants(path: Path) -> dict[str, set[str]]:
        actors = yaml.safe_load(path.read_text(encoding="utf-8"))["actors"]
        return {actor: set(purposes) for actor, purposes in actors.items()}

    # -- access control (S8) ----------------------------------------------

    def _log(self, actor: str, purpose: str, action: str, granted: bool,
             **fields) -> None:
        from engine.contracts import validate
        line = {"ts": _now(), "actor": actor, "purpose": purpose,
                "action": action, "granted": granted, **fields}
        validate("access_log", line)  # a rejected line is a write-site bug
        with open(self.access_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _authorize(self, actor: str, purpose: str, action: str, **fields) -> None:
        granted = purpose in self._grants.get(actor, set())
        self._log(actor, purpose, action, granted, **fields)
        if not granted:
            raise ProvenanceAccessDenied(
                f"actor {actor!r} is not authorized for purpose {purpose!r}"
            )

    # -- writes (ingestion/purge code paths, not access-controlled reads) --

    def _path(self, kb_id: str) -> Path:
        return self.prov_dir / f"{kb_id}.json"

    def write(self, kb_id: str, provenance: dict, identifiers: dict[str, str]) -> None:
        """provenance is the schema-shaped primary object; the file keeps
        the full shape (sources list) so merges can append contributors."""
        source = {
            k: provenance[k]
            for k in ("source_pursuit", "source_client", "date")
            if k in provenance
        }
        record = {
            "sources": [source],
            "ingested_by": provenance.get("ingested_by"),
            "derived_from": list(provenance.get("derived_from", [])),
            "identifiers": dict(identifiers),
        }
        self._atomic_write(self._path(kb_id), record)

    # -- L0 source artifacts (WP13 R2; placement per B59) ------------------
    # Retained source bytes are UN-anonymized client material, so they live
    # behind the same restricted boundary as provenance — the accept clause
    # allows raw text only in the pursuit workspace and here. Writes follow
    # the provenance write posture (ingestion/purge code paths). The READ
    # doors below (existence, meta, the listing) answer to the same law as
    # every other read here — a line first, then the decision (P26b-2,
    # P2-46: they used to answer without one, and the meta carries the
    # real source_client). The raw bytes themselves still have no reader.

    def _source_dir(self) -> Path:
        return self.root / "sources"

    def write_source(self, doc_id: str, raw: bytes, meta: dict) -> None:
        """Retain the L0 artifact, content-hashed, plus a small clock-free
        meta record (source_hash, original filename) for the purge
        accounting to name."""
        src_dir = self._source_dir()
        src_dir.mkdir(parents=True, exist_ok=True)
        path = src_dir / f"{doc_id}.src"
        write_bytes_atomic(path, raw)  # P0-6: the one primitive
        self._atomic_write(src_dir / f"{doc_id}.json", dict(meta))

    def source_exists(self, doc_id: str, *, actor: str, purpose: str) -> bool:
        """An existence oracle over retained client material is a read."""
        self._authorize(actor, purpose, "source_read", doc_id=doc_id)
        return (self._source_dir() / f"{doc_id}.src").exists()

    def source_meta(self, doc_id: str, *, actor: str, purpose: str) -> dict:
        self._authorize(actor, purpose, "source_read", doc_id=doc_id)
        return json.loads(
            (self._source_dir() / f"{doc_id}.json").read_text(
                encoding="utf-8"))

    def source_metas(self, *, actor: str, purpose: str) -> dict[str, dict]:
        """Every retained artifact's meta in one logged read (lineage and
        purge walk all of them; one line per walk, not one per file)."""
        self._authorize(actor, purpose, "source_read")
        src_dir = self._source_dir()
        out: dict[str, dict] = {}
        if not src_dir.is_dir():
            return out
        for src in sorted(src_dir.glob("*.src")):
            meta = src_dir / f"{src.stem}.json"
            if meta.exists():
                out[src.stem] = json.loads(meta.read_text(encoding="utf-8"))
        return out

    def delete_source(self, doc_id: str) -> None:
        """Purge-path removal of a retained L0 artifact and its meta."""
        (self._source_dir() / f"{doc_id}.src").unlink(missing_ok=True)
        (self._source_dir() / f"{doc_id}.json").unlink(missing_ok=True)

    def list_source_ids(self, *, actor: str, purpose: str) -> list[str]:
        self._authorize(actor, purpose, "list_sources")
        if not self._source_dir().is_dir():
            return []
        return sorted(p.stem for p in self._source_dir().glob("*.src"))

    def append_source(self, kb_id: str, provenance: dict,
                      identifiers: dict[str, str],
                      absorbed: str | None = None) -> None:
        """Merge bookkeeping: a near-duplicate's contributing source joins the
        survivor's record so purging either client removes the card (D1).
        `absorbed` is the never-written candidate's content-anchored id —
        folded into derived_from so absorbed_owners() recognizes the same
        content next time (P13/C8: idempotent re-ingest needs the memory
        in BOTH merge branches, not just the candidate-wins one)."""
        record = json.loads(self._path(kb_id).read_text(encoding="utf-8"))
        source = {
            k: provenance[k]
            for k in ("source_pursuit", "source_client", "date")
            if k in provenance
        }
        if source not in record["sources"]:
            record["sources"].append(source)
        record["identifiers"].update(identifiers)
        if absorbed is not None:
            record["derived_from"] = sorted(
                set(record.get("derived_from", [])) | {absorbed})
        self._atomic_write(self._path(kb_id), record)

    def merge_into(self, src_kb_id: str, dst_kb_id: str) -> None:
        """Dedup-merge bookkeeping: the losing card's sources, identifiers,
        and derivation links fold into the survivor's record before the loser
        is deleted, so no client contribution escapes a future purge (D1).

        The loser's OWN id joins the survivor's derived_from too (P13/C8):
        with content-anchored ids the absorbed id IS the absorbed content's
        hash, so this fold is the store's memory that the content already
        lives here — absorbed_owners() reads it to keep re-ingestion
        idempotent instead of re-fighting the merge every round."""
        src = json.loads(self._path(src_kb_id).read_text(encoding="utf-8"))
        dst = json.loads(self._path(dst_kb_id).read_text(encoding="utf-8"))
        for source in src["sources"]:
            if source not in dst["sources"]:
                dst["sources"].append(source)
        dst["identifiers"].update(src["identifiers"])
        dst["derived_from"] = sorted(
            set(dst["derived_from"]) | set(src["derived_from"]) | {src_kb_id}
        )
        self._atomic_write(self._path(dst_kb_id), dst)
        self._path(src_kb_id).unlink()

    def absorbed_owners(self, *, actor: str, purpose: str) -> dict[str, str]:
        """absorbed kb_id -> the surviving card whose record lists it in
        derived_from (the card its content was merged into). One logged
        walk over the provenance records (P26b-2, P2-46: the per-id
        lookup answered without a line, and ingest asked once per
        candidate — the caller now holds the map)."""
        self._authorize(actor, purpose, "absorbed_lookup")
        owners: dict[str, str] = {}
        for path in sorted(self.prov_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            for absorbed in record.get("derived_from", []):
                owners.setdefault(absorbed, path.stem)
        return owners

    def authorize(self, actor: str, purpose: str, action: str = "delete",
                  **fields) -> None:
        """A lane-wide decision with no single record to read — the purge
        of a whole lane authorizes here BEFORE anything is removed, empty
        lane or not (P26b-2, P1-13: an empty lane used to skip the gate
        and delete unlogged). Logs, then refuses."""
        self._authorize(actor, purpose, action, **fields)

    def humans(self, purpose: str) -> list[str]:
        """Named humans holding a purpose — the routing targets for findings
        (R13: an anonymization failure goes to a named human, not a digest)."""
        return sorted(
            actor for actor, purposes in self._grants.items()
            if purpose in purposes and actor != "engine"
        )

    @staticmethod
    def _atomic_write(path: Path, obj: dict) -> None:
        write_json_atomic(path, obj)  # P0-6: the one primitive

    # -- the read paths (every one logs first, then authorizes) ------------

    def read(self, kb_id: str, *, actor: str, purpose: str) -> dict:
        """THE read path for one card's provenance. Purposes: audit | purge |
        right_of_review | anonymization_scan."""
        self._authorize(actor, purpose, "read", kb_id=kb_id)
        return json.loads(self._path(kb_id).read_text(encoding="utf-8"))

    def scan_index(self, *, actor: str = "engine") -> dict[str, list[str]]:
        """kb_id -> original identifier strings, for the anonymization scan
        and the purge sweep. One log line covers the index read."""
        self._authorize(actor, "anonymization_scan", "scan_index")
        index = {}
        for path in sorted(self.prov_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            index[path.stem] = sorted(record["identifiers"])
        return index

    def reverse_index(self, name: str, *, actor: str) -> list[dict]:
        """Right of review (THREAT_MODEL "Data lifecycle"): answer 'where is
        my name used?' across the corpus."""
        self._authorize(actor, "right_of_review", "reverse_index", name=name)
        needle = name.casefold()
        hits = []
        for path in sorted(self.prov_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            for original, placeholder in sorted(record["identifiers"].items()):
                if needle in original.casefold():
                    hits.append({"kb_id": path.stem, "placeholder": placeholder})
            for source in record["sources"]:
                if needle in source.get("source_client", "").casefold():
                    hits.append({"kb_id": path.stem, "placeholder": "source_client"})
        return hits

    def delete(self, kb_id: str, *, actor: str) -> None:
        """Purge path (D1). Logged like every other restricted touch."""
        self._authorize(actor, "purge", "delete", kb_id=kb_id)
        self._path(kb_id).unlink()

    def log_sweep(self, *, actor: str, client: str, clean: bool,
                  name: str | None = None) -> None:
        """The post-purge sweep verdict belongs in the access log — it is the
        evidence the purge honored the client commitment. `name` (C16)
        references the persisted PurgeAccounting file, so the log line
        points at the full five-stage accounting."""
        fields = {"client": client, "clean": clean}
        if name is not None:
            fields["name"] = name
        self._log(actor, "purge", "sweep", True, **fields)
