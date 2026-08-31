"""Research-pack loader — the loader IS the contract (B21(5), B16 class).

A pack is the airgapped mode's external input: an uploaded markdown file with
an `# Research pack:` H1 and one or more `## ` sections whose first non-blank
line is `source: http(s)://...`. The engine never writes a pack — it is
recorded in the run log as an artifact record (kind research_pack, sha256) and
its shape is enforced here, loudly, instead of by a schema (TODO(spec-gap):
formalize the research-pack schema before A1 — packs outlived the stage that
justified deferring it, B29). Every violation raises ResearchPackError
— a malformed pack must fail the run, never thin it silently.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_TITLE_PREFIX = "# Research pack:"
_SOURCE_RX = re.compile(r"^source: (https?://\S+)$")


class ResearchPackError(ValueError):
    def __init__(self, path: Path, why: str):
        self.path = path
        self.why = why
        super().__init__(f"{path}: {why}")


@dataclass
class PackSection:
    heading: str
    source_url: str
    body: str


@dataclass
class ResearchPack:
    path: Path
    sha256: str
    title: str
    sections: list[PackSection]


def load_pack(path: Path) -> ResearchPack:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except FileNotFoundError:
        raise ResearchPackError(path, "pack file not found")
    except UnicodeDecodeError:
        raise ResearchPackError(path, "pack is not utf-8 text")

    lines = text.splitlines()
    head = next((ln for ln in lines if ln.strip()), "")
    if not head.startswith(_TITLE_PREFIX):
        raise ResearchPackError(path, f"first line must start '{_TITLE_PREFIX}'")
    title = head[len(_TITLE_PREFIX):].strip()
    if not title:
        raise ResearchPackError(path, "pack title is empty")

    sections: list[PackSection] = []
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not sections and not starts:
        raise ResearchPackError(path, "pack has no '## ' sections")
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        heading = lines[start][3:].strip()
        chunk = [ln for ln in lines[start + 1:end]]
        first = next((ln for ln in chunk if ln.strip()), "")
        match = _SOURCE_RX.match(first.strip())
        if not match:
            raise ResearchPackError(
                path, f"section '{heading}': first line must be 'source: http(s)://...'")
        source_url = match.group(1)
        body_lines = chunk[chunk.index(first) + 1:]
        body = "\n".join(body_lines).strip()
        if not body:
            raise ResearchPackError(path, f"section '{heading}' has no body text")
        sections.append(PackSection(heading=heading, source_url=source_url, body=body))

    return ResearchPack(path=path, sha256=hashlib.sha256(raw).hexdigest(),
                        title=title, sections=sections)
