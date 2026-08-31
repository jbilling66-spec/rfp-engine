"""In-place firm-template fill (P17/C9 — B73§2's deferral closed).

The firm_default lane's exit door: for a Path-B pursuit planned against
the firm's own template, the drafted section prose FILLS the template in
place — REPLACEMENT, not insertion (the v1 oracle's law, reimplemented):
each answered section's prose takes its "▸ WHAT TO INCLUDE" guidance
box's place, and the "[ Replace with … ]" placeholder table goes too
(the v1 gap FIXED — v1 shipped documents still carrying placeholders).
Anything unanswered keeps its guidance IDENTICAL — the honest outcome —
and is reported in remaining_guidance. Grids, case blocks, the metadata
table, and inline bracketed paragraphs are recorded fill_by_hand
(B75§1e): a human finishes them, visibly, never silently.

Source binding: the template at config/templates/, verified against the
reference_sha256 the path_b_outline checkpoint recorded — the fill only
touches the EXACT template the plan was built against (B74§3b's
digest-bound rule); placement is re-derived by REPARSE + body walk,
never persisted. The output IS the to-the-buyer document for firm_default
pursuits (B75§1d: exports/submission/response.docx — it replaces the
generated render). Prose lands exactly as render_submission would land
it — one exit-door posture, no divergent hygiene.

The verifier is fill-shaped (B75§3c): a body-order stream diff — the
output must equal the source stream with exactly the intended tables
replaced-by-paragraphs or removed, and NOTHING else different. v1 never
round-tripped its fill at all; this lane refuses to hand back a
document it cannot prove.
"""

import hashlib
import shutil
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from engine.contracts import ContractError, validate
from engine.planning.plan import REFERENCE_DEFAULT
from engine.structure.docx_default import parse_default_template

FACTS_NAME = "exports/template-fill-facts.json"
OUTPUT_NAME = "exports/submission/response.docx"

_P_TAG = "}p"
_TBL_TAG = "}tbl"


def _template_source(pursuit):
    frozen = pursuit.read_artifact("plan.frozen.json")
    container = pursuit.read_artifact(frozen.get("slots_ref", "slots.json"))
    if container.get("source_mode") != "firm_default":
        raise ContractError(
            "template fill is the firm_default lane — a buyer-provided "
            "target ships through write-back, not the firm template")
    ckpt = pursuit.checkpoint_payload("path_b_outline")
    ref_sha = ckpt.get("reference_sha256")
    template = REFERENCE_DEFAULT
    actual = hashlib.sha256(template.read_bytes()).hexdigest()
    if actual != ref_sha:
        raise ContractError(
            "the firm template drifted since planning — refusing to fill "
            "a template the frozen plan was not built against (re-run "
            "planning against the current template)")
    return template, ref_sha, frozen, container


def _body_stream(doc) -> list:
    """The document body in order: ('p', text, style) | ('t', cell rows).
    The comparison currency of the fill verifier."""
    stream = []
    for child in doc.element.body.iterchildren():
        if child.tag.endswith(_P_TAG):
            para = Paragraph(child, doc)
            stream.append(("p", para.text,
                           para.style.name if para.style else ""))
        elif child.tag.endswith(_TBL_TAG):
            table = Table(child, doc)
            stream.append(("t", [[cell.text for cell in row.cells]
                                 for row in table.rows]))
    return stream


def _delivered_paragraphs(prose: str) -> list[str]:
    return [part.strip() for part in prose.split("\n\n") if part.strip()]


def _plan_bindings(frozen) -> dict[str, str]:
    """slot_id -> plan section_id, through the slot_ids the architect's
    sections inherited from the template (based_on, P16/C7)."""
    bindings: dict[str, str] = {}
    for section in frozen.get("sections", []):
        for slot_id in section.get("slot_ids", []):
            bindings[slot_id] = section["section_id"]
    return bindings


def compute_fill_facts(pursuit, *, confirmed_by: str, at: str) -> dict:
    """One row per non-header template slot — filled, kept_guidance,
    fill_by_hand, or refused_unnamed; re-derived server-side every time
    (S7: the preview and the run compute the same facts)."""
    template, ref_sha, frozen, _container = _template_source(pursuit)
    envelope = pursuit.read_artifact("drafts/draft.json")
    prose_by_section = {
        s["section_id"]: s.get("prose", "")
        for s in envelope.get("sections", [])
        if s.get("status") == "drafted" and s.get("prose")}
    bindings = _plan_bindings(frozen)
    parsed = parse_default_template(template)

    rows = []
    remaining: list[str] = []
    for slot in parsed.slots:
        if slot.get("is_header"):
            continue
        anchor = slot["source_locator"]["docx_anchor"]
        question = slot.get("question_text", "")
        section_id = bindings.get(slot["slot_id"]) or \
            bindings.get(slot.get("parent", ""), "")
        row = {"section_id": section_id or "", "slot_id": slot["slot_id"],
               "docx_anchor": anchor}
        shape = slot.get("response_shape")
        if shape == "prose" and question.startswith("▸"):
            if not section_id:
                row["decision"] = "refused_unnamed"
                row["reason"] = ("the architect's adapted plan carries no "
                                 "section for this template anchor — "
                                 "guidance kept")
                remaining.append(question)
            elif section_id in prose_by_section:
                row["decision"] = "filled"
                row["reason"] = "drafted section prose replaces the guidance"
                row["paragraphs"] = len(_delivered_paragraphs(
                    prose_by_section[section_id]))
                row["placeholder_removed"] = True
            else:
                row["decision"] = "kept_guidance"
                row["reason"] = ("no drafted prose for this section — its "
                                 "guidance survives identical (the honest "
                                 "outcome)")
                remaining.append(question)
        else:
            row["decision"] = "fill_by_hand"
            row["reason"] = {
                "record": "the metadata table is firm identity — a human "
                          "completes it",
                "table": "grids and case blocks take structured firm "
                         "content, not model prose — a human completes "
                         "them (B75§1e)",
            }.get(shape, "inline bracketed line — needs slot-grain "
                         "drafting Path B does not have (B75§1e, closer "
                         "P18+)")
            if question.startswith("▸"):
                remaining.append(question)

        rows.append(row)

    facts = {
        "pursuit_id": pursuit.pursuit_id,
        "plan_sha256": hashlib.sha256(
            (pursuit.root / "plan.frozen.json").read_bytes()).hexdigest(),
        "draft_sha256": hashlib.sha256(
            (pursuit.root / "drafts" / "draft.json").read_bytes()
        ).hexdigest(),
        "revision_n": int(envelope.get("revision_n", 0)),
        "confirmed_by": confirmed_by,
        "at": at,
        "template_file": str(template),
        "template_sha256": ref_sha,
        "output_file": OUTPUT_NAME,
        "sections": rows,
        "remaining_guidance": remaining,
    }
    validate("template_fill_facts", facts)
    return facts


def preview_template_fill(pursuit, *, at: str) -> dict:
    return compute_fill_facts(pursuit, confirmed_by="(unconfirmed)", at=at)


def _fill_document(doc, facts, prose_by_section) -> dict[int, tuple]:
    """The XML surgery (v1's _replace_box, reimplemented not ported):
    for each filled row, insert the delivered paragraphs BEFORE the
    guidance table's element, remove the guidance table, and remove the
    placeholder table that follows it. Returns the intended-change set
    keyed by body-order TABLE INDEX (placeholders share identical text —
    position, not text, is the identity)."""
    filled = {row["docx_anchor"]: row for row in facts["sections"]
              if row["decision"] == "filled"}
    guidance_for = {}
    for row in facts["sections"]:
        if row["decision"] == "filled":
            guidance_for[row["docx_anchor"]] = row
    # Locate guidance tables by their single-cell text == the slot's
    # question_text; re-derive from the parse so ids match (B74§3b).
    parsed = parse_default_template(Path(facts["template_file"]))
    question_by_anchor = {
        s["source_locator"]["docx_anchor"]: s.get("question_text", "")
        for s in parsed.slots
        if s.get("response_shape") == "prose"
        and s.get("question_text", "").startswith("▸")}

    intended: dict[int, tuple] = {}
    tbl_index = -1
    pending_placeholder_for: str | None = None
    for child in list(doc.element.body.iterchildren()):
        if not child.tag.endswith(_TBL_TAG):
            continue
        tbl_index += 1
        table = Table(child, doc)
        if not table.rows or not table.rows[0].cells:
            continue
        first_cell = table.rows[0].cells[0].text.strip()
        if pending_placeholder_for is not None:
            anchor = pending_placeholder_for
            pending_placeholder_for = None
            if first_cell.startswith("["):
                # the placeholder that trailed a filled guidance box
                intended[tbl_index] = ("remove",)
                child.getparent().remove(child)
                continue
        match = next((a for a, q in question_by_anchor.items()
                      if q == first_cell and a in filled), None)
        if match is None:
            continue
        row = filled.pop(match)
        parts = _delivered_paragraphs(prose_by_section[row["section_id"]])
        parent = child.getparent()
        position = list(parent).index(child)
        anchor_para = doc.add_paragraph()
        for offset, part in enumerate(parts):
            para = doc.add_paragraph(part)
            parent.insert(position + offset, para._element)
        anchor_para._element.getparent().remove(anchor_para._element)
        parent.remove(child)
        intended[tbl_index] = ("replace", parts)
        pending_placeholder_for = match
    if filled:
        raise ContractError(
            "template fill could not locate the guidance box for: "
            + ", ".join(sorted(filled)) + " — the template and the plan "
            "disagree; refusing a partial fill")
    return intended


def _assert_fill_roundtrip(template: Path, output: Path,
                           intended: dict[int, tuple]) -> None:
    """The fill-shaped verifier (B75§3c): the output body stream must
    equal the source stream with EXACTLY the intended tables replaced by
    their delivered paragraphs or removed — untouched paragraphs
    identical in text and style, surviving tables cell-identical."""
    source = Document(str(template))
    expected: list = []
    tbl_index = -1
    for item in _body_stream(source):
        if item[0] != "t":
            expected.append(item)
            continue
        tbl_index += 1
        action = intended.get(tbl_index)
        if action is None:
            expected.append(item)
        elif action[0] == "remove":
            continue
        else:  # replace
            expected.extend(("p", part, "Normal") for part in action[1])
    actual = _body_stream(Document(str(output)))
    if actual != expected:
        raise ContractError(
            "template fill drifted outside the intended sections — "
            "refusing to hand back a document that differs from the "
            "declared change set")


def run_template_fill(pursuit, log, *, confirmed_by: str, at: str) -> dict:
    """Confirm-and-run (S7): facts re-derived server-side, the fill
    applied to a COPY, the stream-diff verifier proving the change set,
    the facts artifact written and logged."""
    facts = compute_fill_facts(pursuit, confirmed_by=confirmed_by, at=at)
    template = Path(facts["template_file"])
    envelope = pursuit.read_artifact("drafts/draft.json")
    prose_by_section = {
        s["section_id"]: s.get("prose", "")
        for s in envelope.get("sections", [])
        if s.get("status") == "drafted" and s.get("prose")}

    output = pursuit.root / OUTPUT_NAME
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    doc = Document(str(output))
    intended = _fill_document(doc, facts, prose_by_section)
    doc.save(str(output))
    _assert_fill_roundtrip(template, output, intended)

    facts_path = pursuit.root / FACTS_NAME
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    facts_path.write_text(
        _json.dumps(facts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    log.emit("artifact", stage="write_back", artifact={
        "kind": "template_fill_facts", "path": str(facts_path),
        "revision_n": facts["revision_n"],
        "sha256": hashlib.sha256(facts_path.read_bytes()).hexdigest()})
    log.emit("artifact", stage="write_back", artifact={
        "kind": "export", "path": str(output),
        "revision_n": facts["revision_n"],
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest()})
    return facts
