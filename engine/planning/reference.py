"""Firm reference — read from the FIRM TEMPLATE itself (P16/C7).

B67§1 named the old markdown "free-flow skeleton" a misnomer:
free-form-to-the-buyer is TEMPLATE-driven for the firm. The reference
the Outline Architect adapts is now built by PARSING the firm's own
Word template (config/templates/, the adopter-configuration surface —
B68§5): section ids are slugs of the template's numbered H1 titles,
purposes are the template's own "WHAT TO INCLUDE" guidance, and each
reference section carries the TargetSlot ids the template parser
produced for it — so an architect section based_on a reference section
inherits real, write-back-capable slots instead of a bare title.

Loader-is-the-contract (B16/B21(5) class): firm config, so a missing
or unparseable template RAISES loudly, never refuses. The file is
digest-visible run config (folded into config_digest via
effective_config(extra=...) alongside the manifest).
"""

from dataclasses import dataclass, field
from pathlib import Path

from engine.planning.sections import unique_slugs

_GUIDANCE_PREFIX = "▸ WHAT TO INCLUDE"


class ReferenceError(ValueError):
    """The firm template violated its contract (named file, named reason)."""


@dataclass
class ReferenceOutline:
    path: Path
    sections: list[dict] = field(default_factory=list)
    # {id, title, purpose, slot_ids} per top-level template section
    parsed: object | None = None  # the full ParsedWorkbook (firm_default)

    def ids(self) -> list[str]:
        return [s["id"] for s in self.sections]


def _purpose(children: list[dict], title: str) -> str:
    for child in children:
        text = (child.get("question_text") or "").strip()
        if text.startswith(_GUIDANCE_PREFIX):
            return text[len(_GUIDANCE_PREFIX):].lstrip(" —-–:").strip()
    return title


def load_reference(path: Path) -> ReferenceOutline:
    from engine.structure import StructureError, parse_default_template

    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ReferenceError(
            f"{path.name}: the firm template is a .docx (P16/C7 — the "
            "markdown reference retired); got suffix "
            f"{path.suffix!r}")
    try:
        parsed = parse_default_template(path)
    except StructureError as exc:
        raise ReferenceError(str(exc)) from exc

    headers = [s for s in parsed.slots
               if s.get("is_header") and not s.get("parent")]
    if not headers:
        raise ReferenceError(
            f"{path.name}: no top-level numbered sections in the template")
    children_by_parent: dict[str, list[dict]] = {}
    for slot in parsed.slots:
        parent = slot.get("parent")
        if parent:
            children_by_parent.setdefault(parent, []).append(slot)

    sections = []
    titles = [(h.get("question_text") or h["slot_id"]).strip()
              for h in headers]
    for header, title, sid in zip(headers, titles, unique_slugs(titles)):
        children = children_by_parent.get(header["slot_id"], [])
        sections.append({
            "id": sid,
            "title": title,
            "purpose": _purpose(children, title),
            "slot_ids": [header["slot_id"]]
                        + [c["slot_id"] for c in children],
        })
    return ReferenceOutline(path=path, sections=sections, parsed=parsed)


def render_reference(outline: ReferenceOutline) -> str:
    """The deterministic block the architect prompt inlines: one line per
    section, `id | title | purpose` — ids are what based_on cites."""
    return "\n".join(
        f"- {s['id']} | {s['title']} | {s['purpose']}" for s in outline.sections
    )
