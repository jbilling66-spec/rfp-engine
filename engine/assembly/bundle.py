"""The submission bundle (P18/C3, B77§2 D2-D3): the to-the-buyer
deliverable set as a RECORD, not a directory listing.

Two jobs live here:

- `declared_deliverables(pursuit, container)` answers "which write-back
  lanes does this pursuit's container owe?" — one binding per declared
  source (the fNN merge prefix the slot ids already carry keys the
  per-file facts names, so nothing collides by construction), or the
  fill lane for firm_default. This replaces the web layer's one-string
  dispatcher (P17/C10): the engine, not the route, knows the
  deliverable set.

- `compose_bundle(pursuit, log, ...)` derives the EXPECTED set from the
  container — never from the filesystem — and records each deliverable's
  tri-state: produced (bytes on disk, digested, decision record
  attached), refused (its lane ran and said no, reason carried), or
  absent (expected and not yet produced — the RECORDED absence the P18
  row exists for; a bundle that silently misses a form is the failure
  mode). v1 PlacementRun's law at the bundle grain: the composer
  OVERWRITES (current-state record; history is the run log's artifact
  lines), and no-bundle-file means never composed.

Two entries sharing a basename refuse loudly at compose time — the
downloads listing shows basenames, and v1's resolve-by-sort-order
collision is banned (B77§3).
"""

import hashlib
from pathlib import Path

from engine.contracts import ContractError

BUNDLE_NAME = "exports/submission-bundle.json"
RENDER_NAME = "exports/submission/response.docx"

_FACTS_BASE = {"xlsx_writeback": "exports/writeback-facts",
               "docx_writeback": "exports/docx-writeback-facts"}


def _lane_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        return "xlsx_writeback"
    if suffix == ".docx":
        return "docx_writeback"
    raise ContractError(
        f"declared source {filename!r} has no write-back lane — "
        "parse_target admits only xlsx/docx, so this container is out "
        "of contract")


def _flat_source_name(pursuit, container) -> str | None:
    """A flat (single-source) container names its file in the slot
    locators only when a docx parser built it; the xlsx parser does not
    stamp file. The digest IS the identity either way (the exact-file
    rule), so fall back to matching the inbox against it."""
    for slot in container.get("slots", []):
        name = slot.get("source_locator", {}).get("file")
        if name:
            return name
    digest = container.get("source_sha256")
    inbox = pursuit.root / "inbox"
    candidates = sorted(inbox.iterdir()) if inbox.exists() else []
    for candidate in candidates:
        if candidate.suffix.lower() not in (".xlsx", ".docx"):
            continue
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
            return candidate.name
    return None


def declared_deliverables(pursuit, container) -> list[dict]:
    """One binding per write-back deliverable the container declares:
    {lane, file, source_sha256, prefix, facts_name, output_name}.
    firm_default owes exactly the filled template (B75§1d); a multi-source
    container owes one per sources[] entry; a flat container owes one,
    under the LEGACY facts name so every existing record stays true
    (B77§2 D1)."""
    if container.get("source_mode") == "firm_default":
        return [{"lane": "template_fill", "file": None,
                 "source_sha256": None, "prefix": "",
                 "facts_name": "exports/template-fill-facts.json",
                 "output_name": RENDER_NAME}]
    sources = container.get("sources")
    if sources:
        bindings = []
        for i, entry in enumerate(sources):
            lane = _lane_for(entry["file"])
            tag = f"f{i:02d}"
            bindings.append({
                "lane": lane, "file": entry["file"],
                "source_sha256": entry["source_sha256"],
                "prefix": f"{tag}-",
                "facts_name": f"{_FACTS_BASE[lane]}-{tag}.json",
                "output_name": f"exports/writeback/{entry['file']}"})
        return bindings
    name = _flat_source_name(pursuit, container)
    if name is None:
        raise ContractError(
            "the container names no source file and nothing in inbox/ "
            "matches its source_sha256 — the deliverable set cannot be "
            "derived from a source that does not exist")
    lane = _lane_for(name)
    return [{"lane": lane, "file": name,
             "source_sha256": container.get("source_sha256"), "prefix": "",
             "facts_name": f"{_FACTS_BASE[lane]}.json",
             "output_name": f"exports/writeback/{name}"}]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(pursuit, binding: dict, refusals: list[dict]) -> dict:
    out = {"name": Path(binding["output_name"]).name,
           "path": binding["output_name"], "lane": binding["lane"]}
    if binding["file"]:
        out["source_file"] = binding["file"]
    for refusal in refusals:
        if (refusal.get("lane") == binding["lane"]
                and refusal.get("file") == binding["file"]):
            out["status"] = "refused"
            out["reason"] = refusal["reason"]
            return out
    facts_path = pursuit.root / binding["facts_name"]
    output_path = pursuit.root / binding["output_name"]
    if facts_path.is_file() and output_path.is_file():
        facts = pursuit.read_artifact(binding["facts_name"])
        out["status"] = "produced"
        out["sha256"] = _sha256(output_path)
        out["facts_path"] = binding["facts_name"]
        out["revision_n"] = facts["revision_n"]
        return out
    out["status"] = "absent"
    return out


def _render_entry(pursuit, refusals: list[dict]) -> dict:
    out = {"name": Path(RENDER_NAME).name, "path": RENDER_NAME,
           "lane": "submission_render"}
    for refusal in refusals:
        if refusal.get("lane") == "submission_render":
            out["status"] = "refused"
            out["reason"] = refusal["reason"]
            return out
    output_path = pursuit.root / RENDER_NAME
    if output_path.is_file():
        out["status"] = "produced"
        out["sha256"] = _sha256(output_path)
        return out
    out["status"] = "absent"
    return out


def compose_bundle(pursuit, log, *, at: str, composed_by: str,
                   refusals: list[dict] | None = None) -> dict:
    """Derive the expected set from the CONTAINER, read what each lane
    actually left on disk, and overwrite exports/submission-bundle.json.
    `refusals` is the calling door's record of lanes that ran and
    refused THIS pass: [{lane, file, reason}] — a refusal is an event
    the filesystem cannot show, so the door that saw it carries it in."""
    frozen_plan = pursuit.read_artifact("plan.frozen.json")
    container = pursuit.read_artifact(
        frozen_plan.get("slots_ref", "slots.json"))
    bindings = declared_deliverables(pursuit, container)
    deliverables = [_entry(pursuit, b, refusals or []) for b in bindings]
    if container.get("source_mode") != "firm_default":
        deliverables.append(_render_entry(pursuit, refusals or []))
    names = [d["name"] for d in deliverables]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ContractError(
            f"submission bundle basename collision: {duplicated} — the "
            "downloads listing shows basenames, so two deliverables may "
            "not share one (v1 resolved this by sort order; refused "
            "here instead)")
    bundle = {"pursuit_id": pursuit.pursuit_id, "at": at,
              "composed_by": composed_by, "deliverables": deliverables}
    path = pursuit.write_artifact("submission_bundle", bundle,
                                  name=BUNDLE_NAME)
    revision_n = 0
    if (pursuit.root / "drafts" / "draft.json").is_file():
        revision_n = pursuit.read_artifact(
            "drafts/draft.json").get("revision_n", 0)
    log.emit("artifact", stage="write_back", artifact={
        "kind": "submission_bundle", "path": str(path),
        "revision_n": revision_n, "sha256": _sha256(path)})
    return bundle
