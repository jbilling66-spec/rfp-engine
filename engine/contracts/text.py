"""Prose hygiene at the contract boundary (P26a, P2-29b).

python-docx refuses XML-incompatible text at the exit door with a bare
ValueError ("All strings must be XML compatible") — P25 item 8 made both
doors close the run on it, but that is hours after the character entered
the envelope. This is the typed refusal at the ENTRY: every writer of
prose (the drafting lane, the revision round, the human-edit and guest
comment doors, the hand-completion door) asks here first, so a control
character never reaches drafts/draft.json.
"""

import re

# C0 controls except TAB/LF/CR (XML 1.0's own rule), plus DEL. \x0b and
# \x0c are inside the range on purpose — they are the verified offenders.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def check_prose(text: str) -> str | None:
    """None when `text` is XML-safe; otherwise a short reason naming the
    first offending character (by codepoint, never by reproducing it)."""
    if not isinstance(text, str):
        return f"expected text, got {type(text).__name__}"
    m = _CONTROL.search(text)
    if m is None:
        return None
    return (f"control character U+{ord(m.group()):04X} at offset "
            f"{m.start()} — XML-incompatible, refused")
