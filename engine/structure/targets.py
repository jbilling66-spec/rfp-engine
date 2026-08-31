"""The declared-target surface (P16/C4): any response vehicle in, one
slot vocabulary out.

parse_target       dispatch by document type — a declared target the
                   engine cannot classify FAILS LOUDLY (StructureError),
                   never degrading to free_flow. The xlsx lane is the
                   byte-pinned pre-P16 parser, untouched.
scan_core_document opportunistic sweep of a CORE narrative document for
                   embedded response structure (B67-F3): mandated
                   numbered sections and fill-in tables inside the
                   prose. Finding nothing is normal (None/empty). A PDF
                   core cannot be scanned offline — that is a RECORDED
                   limitation (the caller flags it; closer A1/extraction,
                   the F4 precedent), never a silent skip.
merge_parsed       one container body from one-or-many parses. A single
                   target writes EXACTLY the pre-P16 shape (the byte
                   pin); a multi-file set namespaces slot ids per file
                   (f00-, f01-, …), remaps parent/gates references, and
                   carries per-file provenance in sources[] (C4a schema).
"""

from pathlib import Path

from engine.structure.docx_buyer import parse_buyer_docx
from engine.structure.parse import (
    ParsedWorkbook,
    StructureError,
    parse_workbook,
)

_XLSX = {".xlsx"}
_DOCX = {".docx"}


def parse_target(path: Path) -> ParsedWorkbook:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in _XLSX:
        return parse_workbook(path)
    if suffix in _DOCX:
        return parse_buyer_docx(path)
    raise StructureError(
        f"{path.name}: declared target of unsupported type {suffix!r} — "
        "refusing loudly; a declared target never degrades to free_flow"
    )


def scan_core_document(path: Path) -> ParsedWorkbook | None:
    path = Path(path)
    if path.suffix.lower() not in _DOCX:
        return None  # caller decides how loudly to record the limitation
    return parse_buyer_docx(path, core_scan=True)


def _prefixed(slot: dict, prefix: str, ids: set[str]) -> dict:
    out = dict(slot)
    out["slot_id"] = f"{prefix}{slot['slot_id']}"
    if slot.get("parent") in ids:
        out["parent"] = f"{prefix}{slot['parent']}"
    gating = slot.get("gating")
    if gating:
        remapped = dict(gating)
        if "gates" in gating:  # gates hold slot_ids; gated_by holds a ref
            remapped["gates"] = [
                f"{prefix}{g}" if g in ids else g for g in gating["gates"]
            ]
        out["gating"] = remapped
    return out


def merge_parsed(parsed: list[ParsedWorkbook]) -> dict:
    if not parsed:
        raise StructureError("merge_parsed: nothing to merge")
    if len(parsed) == 1:
        p = parsed[0]
        return {
            "source_mode": p.source_mode,
            "parser_version": p.parser_version,
            "source_sha256": p.source_sha256,
            "slot_count": p.slot_count,
            "slots": p.slots,
        }
    slots: list[dict] = []
    sources: list[dict] = []
    for i, p in enumerate(parsed):
        prefix = f"f{i:02d}-"
        ids = {s["slot_id"] for s in p.slots}
        slots.extend(_prefixed(s, prefix, ids) for s in p.slots)
        sources.append({
            "file": p.file,
            "source_sha256": p.source_sha256,
            "parser_version": p.parser_version,
        })
    first = parsed[0]
    return {
        "source_mode": first.source_mode,
        "parser_version": first.parser_version,
        "source_sha256": first.source_sha256,
        "slot_count": len(slots),
        "slots": slots,
        "sources": sources,
    }
