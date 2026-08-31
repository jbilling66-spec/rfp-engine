"""The assistant's grounding corpus: the steward docs plus the advisor
docs, as a CLOSED filename tuple (the advisor's D21 pattern, one level
up). Filenames are the citation vocabulary; the docs are fetched by the
`read_doc` TOOL rather than concatenated into the system prompt, so
"cite it" requires "retrieved it" — every doc read is a tool_call line
on the session's run log, and the citation gate refuses a name the
session never fetched."""

from pathlib import Path

from engine.support.advisor import DOC_SOURCES as ADVISOR_SOURCES

ROOT = Path(__file__).resolve().parents[2]
STEWARD_DIR = ROOT / "docs" / "steward"
ADVISOR_DIR = ROOT / "docs" / "advisor"

STEWARD_SOURCES = ("steward-runbook.md", "maintenance-guide.md",
                   "success-strategies.md")
DOC_SOURCES: tuple[str, ...] = STEWARD_SOURCES + ADVISOR_SOURCES

_MISSING = "(unavailable — this document is missing from the install)"


def _path(name: str) -> Path:
    return (STEWARD_DIR if name in STEWARD_SOURCES else ADVISOR_DIR) / name


def corpus_toc() -> str:
    """One line per doc — name plus its title heading — rendered into the
    system prompt so the model knows what EXISTS; it must read_doc to
    quote or cite. Deterministic; a missing doc shows honestly."""
    lines = []
    for name in DOC_SOURCES:
        path = _path(name)
        title = _MISSING
        if path.exists():
            first = path.read_text(encoding="utf-8").splitlines()[0]
            title = first.lstrip("# ").strip()
        lines.append(f"- {name}: {title}")
    return "\n".join(lines)


def read_doc(name: str) -> str:
    """The whole doc, or a loud refusal for a name outside the closed
    vocabulary. A missing file returns the marker — the assistant then
    honestly cannot quote it (the advisor's rule)."""
    if name not in DOC_SOURCES:
        raise ValueError(
            f"{name!r} is not a grounding document — the corpus is "
            f"{', '.join(DOC_SOURCES)}")
    path = _path(name)
    return path.read_text(encoding="utf-8") if path.exists() else _MISSING
