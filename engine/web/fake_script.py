"""The revision arm of the product-side FakeCaller script (B37/D6) —
the derive-from-prompt house pattern: the regexes here are the SAME
formats engine/revision/compose.py renders, so a composer change fails
the CI revise flavor and the revision fixtures together, never silently
apart. Zero imports from tests/ (slice_script's discipline)."""

import json
import re

from engine.cli.slice_script import ci_script

# compose.review_comments_frame / external_comments_frame line format
_CID_RX = re.compile(r"^\[(cmt_\d+)\]", re.M)
# compose.current_prose_block slot lines ("SLOT <id>:" — distinct from
# the directive's "SLOT <id> | ref" lines)
_SLOT_PROSE_RX = re.compile(
    r"^SLOT (\S+):\n(.*?)(?=\nSLOT \S+:\n|\n\n|\Z)", re.M | re.S)
# the Path-B return-shape sentinel in compose.revision_directive
_PATH_B_RX = re.compile(r'Return \{"prose"')
# compose.revision_directive's answered-gap line (D15)
_GAP_ANSWER_RX = re.compile(
    r"^- GAP ANSWERED for slot (\S+): .*draft that slot with it: (.*)$",
    re.M)
_CURRENT_RX = re.compile(
    r"CURRENT DRAFT \(the text under revision\):\n(.*?)(?=\n\n<|\n\nREVISE)",
    re.S)


def derive_revision_wire(prompt: str) -> str:
    cids = _CID_RX.findall(prompt)
    suffix = f" [revised per {'+'.join(cids) or 'directives'}]"
    replies = [{"event_id": cid, "reply": f"Addressed {cid}."}
               for cid in cids]
    current = _CURRENT_RX.search(prompt)
    block = current.group(1) if current else ""
    slots = _SLOT_PROSE_RX.findall(block)
    gap_answers = _GAP_ANSWER_RX.findall(prompt)
    if (slots or gap_answers) and not _PATH_B_RX.search(prompt):
        answers = [{"slot_id": slot_id, "prose": prose.strip() + suffix,
                    "kb_ids": []} for slot_id, prose in slots]
        drafted = {a["slot_id"] for a in answers}
        answers += [{"slot_id": slot_id,
                     "prose": f"Drafted from the gap answer: {content}",
                     "kb_ids": []}
                    for slot_id, content in gap_answers
                    if slot_id not in drafted]
        return json.dumps({"answers": answers, "replies": replies})
    prose = (block.strip().splitlines() or [""])[-1] if not slots else ""
    return json.dumps({"prose": (block.strip() or "prose") + suffix,
                       "kb_ids": [], "replies": replies})


def revision_script() -> dict:
    """ci_script + the revision arm — the web revise job's CI flavor."""
    script = ci_script()
    script["revision_agent"] = derive_revision_wire
    return script
