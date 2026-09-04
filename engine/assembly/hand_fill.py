"""The hand-completion door for the firm_default lane (P26a item 1,
P1-27 — the owner's call, 2026-09-02).

The bundled firm template carries four shapes the engine never drafts:
the proposal-metadata RECORD (the `Field` table), the pricing GRID, the
case BLOCK, and the inline bracketed line. Before this door a human
finished them in Word after download, which meant the buyer-facing
document could never be complete from the engine's side. This door takes
the values (typed by a human, computed by nobody — a fee is a string;
P3-1's pricing scope is untouched), validates them against the SLOTS
the parser already addresses, and records them in exports/hand-fill.json
for the fill to render in place. Last write wins per slot; every write
is server-stamped (entered_by from the session, at from the server
clock); an empty value clears a slot.
"""

import re

from engine.contracts import ContractError, validate
from engine.contracts.text import check_prose

HAND_FILL_NAME = "exports/hand-fill.json"
_NUMERIC_TYPES = {"number", "currency", "percent"}
_NUMERIC_NOISE = re.compile(r"[,\s$€£%]")
_BOOLEAN_WORDS = {"yes", "no", "true", "false", "y", "n"}


def is_hand_slot(slot: dict) -> bool:
    """A slot a human completes: record and table shapes, and the
    bracketed inline line (a prose slot with a `[` and no `▸`
    guidance — docx_default.py's inline case)."""
    if slot.get("is_header"):
        return False
    shape = slot.get("response_shape")
    if shape in ("record", "table"):
        return True
    question = slot.get("question_text", "")
    return shape == "prose" and "[" in question \
        and not question.startswith("▸")


def hand_slots(container) -> list[dict]:
    """Container dict (slots.json) or ParsedWorkbook alike."""
    slots = (container.slots if hasattr(container, "slots")
             else container.get("slots", []))
    return [s for s in slots if is_hand_slot(s)]


def _fields(slot: dict) -> list[dict]:
    return list(slot.get("response_fields") or [])


def case_block_slots(container) -> list[dict]:
    """P26c (P1-44): the hand slots whose typed content the corpus may
    learn from — a CASE BLOCK: table-shaped, no numeric-typed field, no
    field addressed by a column (the pricing grid's locator, so a fee
    never rides into a proposal — P3-1). The metadata record and the
    inline line describe THIS pursuit and stay with it."""
    out = []
    for slot in hand_slots(container):
        if slot.get("response_shape") != "table":
            continue
        fields = _fields(slot)
        if any(f.get("type", "text") in _NUMERIC_TYPES for f in fields):
            continue
        if any("column" in (f.get("source_locator") or {}) for f in fields):
            continue
        out.append(slot)
    return out


def case_block_text(slot: dict, entries: list[dict]) -> str:
    """One `Label: value` line per field, one blank line per entry —
    the render the template fill uses, and the body a case-study
    proposal carries."""
    fields = _fields(slot)
    blocks = []
    for entry in entries or []:
        blocks.append("\n".join(
            f"{f['label']}: {entry.get(f['key'], '')}" for f in fields))
    return "\n\n".join(blocks)


def _check_scalar(slot_id: str, key: str, ftype: str, value) -> str:
    if not isinstance(value, str):
        raise ContractError(
            f"{slot_id}.{key}: must be text, got {type(value).__name__}")
    bad = check_prose(value)
    if bad:
        raise ContractError(f"{slot_id}.{key}: {bad}")
    text = value.strip()
    if not text:
        return ""
    if ftype in _NUMERIC_TYPES:
        try:
            float(_NUMERIC_NOISE.sub("", text))
        except ValueError:
            raise ContractError(
                f"{slot_id}.{key}: a {ftype} field must parse as a number "
                f"(got {text!r})") from None
    elif ftype == "boolean" and text.lower() not in _BOOLEAN_WORDS:
        raise ContractError(
            f"{slot_id}.{key}: a boolean field takes yes/no (got {text!r})")
    return text


def _check_entry(slot: dict, entry, *, what: str) -> dict:
    slot_id = slot["slot_id"]
    if not isinstance(entry, dict):
        raise ContractError(
            f"{slot_id}: {what} must be an object of field values, got "
            f"{type(entry).__name__}")
    fields = {f["key"]: f for f in _fields(slot)}
    unknown = sorted(set(entry) - set(fields))
    if unknown:
        raise ContractError(
            f"{slot_id}: unknown field(s) {unknown} — this slot's fields "
            f"are {sorted(fields)}")
    out = {}
    for key, value in entry.items():
        text = _check_scalar(slot_id, key, fields[key].get("type", "text"),
                             value)
        if text:
            out[key] = text
    return out


def normalize_values(container: dict, values) -> dict:
    """Validate a PUT payload's `values` against the container; return
    the normalized mapping (stripped text, empties dropped, cleared slots
    mapped to None). Typed refusals name the slot and field."""
    if not isinstance(values, dict):
        raise ContractError("values must be an object of slot_id -> value")
    by_id = {s["slot_id"]: s for s in container.get("slots", [])}
    out: dict = {}
    for slot_id, value in values.items():
        slot = by_id.get(slot_id)
        if slot is None:
            raise ContractError(f"{slot_id}: not a slot of this template")
        if not is_hand_slot(slot):
            raise ContractError(
                f"{slot_id}: drafted by the engine from the plan, not "
                f"completed by hand")
        shape = slot.get("response_shape")
        if shape == "record":
            if value in (None, {}, ""):
                out[slot_id] = None
                continue
            entry = _check_entry(slot, value, what="a record")
            out[slot_id] = entry or None
        elif shape == "table":
            if value in (None, [], ""):
                out[slot_id] = None
                continue
            if not isinstance(value, list):
                raise ContractError(
                    f"{slot_id}: a table slot takes a list of rows/entries")
            rows = [_check_entry(slot, e, what="each row") for e in value]
            rows = [r for r in rows if r]
            out[slot_id] = rows or None
        else:  # the inline bracketed line
            if value is None:
                out[slot_id] = None
                continue
            text = _check_scalar(slot_id, "value", "text", value)
            out[slot_id] = text or None
    return out


def read_hand_fill(pursuit) -> dict | None:
    path = pursuit.root / HAND_FILL_NAME
    if not path.is_file():
        return None
    return pursuit.read_artifact(HAND_FILL_NAME)


def write_hand_fill(pursuit, *, container: dict, template_sha256: str,
                    entered_by: str, at: str, values) -> dict:
    """Merge one PUT into the record (last write wins per slot; None
    clears) and write it atomically through the contract door. Values
    recorded against a DIFFERENT template are discarded, not carried."""
    incoming = normalize_values(container, values)
    existing = read_hand_fill(pursuit)
    merged: dict = {}
    if existing and existing.get("template_sha256") == template_sha256:
        merged.update(existing.get("values", {}))
    for slot_id, value in incoming.items():
        if value is None:
            merged.pop(slot_id, None)
        else:
            merged[slot_id] = value
    record = {"pursuit_id": pursuit.pursuit_id,
              "template_sha256": template_sha256,
              "entered_by": entered_by, "at": at, "values": merged}
    validate("hand_fill", record)
    pursuit.write_artifact("hand_fill", record, name=HAND_FILL_NAME)
    return record


def completeness(slot: dict, value) -> tuple[bool, list[str]]:
    """(complete, missing) — a record needs every field; a table needs at
    least one row/entry with every field; the inline line needs text."""
    keys = [f["key"] for f in _fields(slot)]
    shape = slot.get("response_shape")
    if shape == "record":
        got = value or {}
        missing = [k for k in keys if not got.get(k)]
        return (not missing, missing)
    if shape == "table":
        rows = value or []
        if not rows:
            return False, ["at least one row"]
        missing = sorted({k for row in rows for k in keys if not row.get(k)})
        return (not missing, missing)
    return (bool(value), [] if value else ["the bracketed value"])


def catalogue(container: dict, values: dict | None) -> list[dict]:
    """What a human owes, slot by slot — the reader the record needed."""
    values = values or {}
    out = []
    for slot in hand_slots(container):
        value = values.get(slot["slot_id"])
        complete, missing = completeness(slot, value)
        out.append({
            "slot_id": slot["slot_id"],
            "path": slot.get("path", ""),
            "docx_anchor": slot["source_locator"].get("docx_anchor", ""),
            "shape": slot.get("response_shape"),
            "fields": [{"key": f["key"], "label": f["label"],
                        "type": f.get("type", "text")}
                       for f in _fields(slot)],
            "status": "filled" if complete else "owed",
            "missing": missing,
            "value": value,
        })
    return out
