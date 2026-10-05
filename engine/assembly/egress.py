"""The egress gate (P32a, A6's pre-export leakage scan — THREAT_MODEL T2):
every exit lane scans the exact set of strings it is about to hand
outward, against the identifiers the knowledge base has ever ingested,
and refuses typed when another client's identifier is in the text.

One scanner, not a second detector: `scan_egress` wraps the ingest
scanner (`engine.kb.anonymize.scan`) over a location-keyed text set the
calling lane builds — the ingest's own "the scan set IS the writer set"
discipline (`ingest.persisted_texts`), applied at the exit. The
identifier universe is the restricted provenance index read under the
engine's `anonymization_scan` grant (one access-log line per export),
minus this pursuit's own buyer (its name belongs in its proposal) and
the firm (its own name is on every page).

The report names LOCATIONS, CLASSES and COUNTS — never the matched
text and never an identifier value (CLAUDE.md rule 6, the run-log
rule): an index residue is classed by a digest of the identifier, a
structured hit by its bracketed class. Policy (the owner's call,
2026-10-04): an index residue BLOCKS; structured classes (emails,
phones, addresses, tax ids, reference numbers) are counted and reported
but do not block in this slice — a firm e-mail in a real proposal must
not train operators to override the refusal. Reopen: A1's first real
draft shows index misses → structured blocking per class.
"""

from dataclasses import dataclass, field
from pathlib import Path

from engine.assembly.hygiene import firm_identity
from engine.contracts import ContractError
from engine.kb.anonymize import normalize_text, scan
from engine.runlog import digest
from engine.workspace.buyer import buyer_identifiers

CHECK = "pre_export_leakage"
INDEX_CLASS = "kb_identifier"


class EgressResidue(ContractError):
    """The exit refused: another client's identifier is in the outgoing
    text. A ContractError (the doors already type it as a 409) with its
    own name so a door can carry it into the bundle record."""


def store_for(workspace, store=None):
    """The store whose restricted index the exit scans: the caller's
    (the server always passes its own), else the workspace's own `kb/`
    (the fixture-chain layout), else none — then the universe is empty
    and the scan still runs the structured classes and records its line.
    Never the committed product store by implication: that resolution
    belongs to the door that knows its root."""
    if store is not None:
        return store
    from engine.kb.store import KBStore
    kb_root = Path(workspace) / "kb"
    return KBStore(kb_root) if kb_root.is_dir() else None


def egress_identifiers(workspace, pursuit, store) -> set[str]:
    """The identifier universe for one pursuit's exit: every original
    identifier string in the restricted provenance index, minus the
    pursuit's own buyer names (brief + org aliases) and the firm's name
    and company. Normalized the way the scanner normalizes. `store` may
    be None (see `store_for`): then the universe is empty."""
    index = store.restricted.scan_index(actor="engine") if store else {}
    universe = {normalize_text(value).strip()
                for values in index.values() for value in values}
    own = {name.casefold() for name in buyer_identifiers(workspace, pursuit)}
    firm = firm_identity(workspace)
    own |= {normalize_text(v).strip().casefold()
            for v in (firm.get("name", ""), firm.get("company", "")) if v}
    return {value for value in universe
            if value and value.casefold() not in own}


@dataclass
class EgressReport:
    """What one lane's scan found: rows of {id, location, class, count}
    (value-free by construction) and which rows block."""
    lane: str
    rows: list[dict] = field(default_factory=list)

    @property
    def blocking(self) -> list[dict]:
        return [row for row in self.rows
                if row["class"].startswith(INDEX_CLASS + ":")]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict:
        return {"check": CHECK, "lane": self.lane, "passed": self.passed,
                "rows": [dict(row) for row in self.rows]}


def _row_class(identifier: str) -> str:
    # a structured hit carries its bracketed class label as the identifier
    if identifier.startswith("<") and identifier.endswith(">"):
        return identifier
    return f"{INDEX_CLASS}:{digest(identifier)}"


def scan_egress(lane: str, texts: dict[str, str],
                identifiers: set[str]) -> EgressReport:
    """Scan `texts` (location label → outgoing string) against
    `identifiers`. Findings collapse to one row per (location, class);
    `count` is how many distinct identifiers (or structured values) of
    that class the location carries. The scanner's matched text never
    leaves this function."""
    groups: dict[tuple[str, str], int] = {}
    for finding in scan(texts, identifiers):
        key = (finding.location, _row_class(finding.identifier))
        groups[key] = groups.get(key, 0) + 1
    rows = [{"id": f"eg_{digest(lane + '|' + location + '|' + cls)[7:19]}",
             "location": location, "class": cls, "count": count}
            for (location, cls), count in sorted(groups.items())]
    return EgressReport(lane=lane, rows=rows)


def residue_message(report: EgressReport) -> str:
    """The refusal in the record's own words — locations and counts, no
    values: "<lane>: identifier residue at 2 location(s) — sec-01:answer:0
    (1), sec-03:prose (2) — ...". Classes are not spelled out here (a
    digest tells an operator nothing); the report row carries them."""
    rows = report.blocking
    where = ", ".join(f"{row['location']} ({row['count']})" for row in rows)
    return (f"{report.lane}: identifier residue at {len(rows)} location(s)"
            f" — {where} — another client's identifier is in the outgoing"
            " text; the exit never opens over it (A6 pre-export scan)."
            " Fix the text and run the exit again")


def emit_scan(log, report: EgressReport, *, agent: str) -> None:
    """The run-log line (`validation.check = pre_export_leakage`, already
    in the contract since B13): block or pass, nothing else — the row
    detail stays on the report and in the bundle's refusal reason."""
    log.emit("validation", stage="write_back", agent=agent,
             validation={"check": CHECK,
                         "result": "block" if not report.passed else "pass"})


def hand_texts(values: dict) -> dict[str, str]:
    """The hand-completion record flattened to location → string, the
    way the template fill writes it: a scalar `hand:<slot>`, a record
    `hand:<slot>:<key>`, a table `hand:<slot>:<i>:<key>`."""
    out: dict[str, str] = {}
    for slot, value in sorted((values or {}).items()):
        if isinstance(value, str):
            out[f"hand:{slot}"] = value
        elif isinstance(value, dict):
            for key, v in sorted(value.items()):
                out[f"hand:{slot}:{key}"] = str(v)
        elif isinstance(value, list):
            for i, entry in enumerate(value):
                for key, v in sorted((entry or {}).items()):
                    out[f"hand:{slot}:{i}:{key}"] = str(v)
    return out


def guest_texts(model: dict) -> dict[str, str]:
    """Every string the guest page renders from the review model
    (`state.review(include_internal=False)`): section titles, each
    slot's prose, each mark's line and the string fields of its detail
    — keyed by location so a mint refusal can name where."""
    out: dict[str, str] = {}
    for section in model.get("sections", []):
        sid = section.get("section_id", "?")
        if section.get("title"):
            out[f"{sid}:title"] = section["title"]
        for i, slot in enumerate(section.get("slots", [])):
            if slot.get("prose"):
                out[f"{sid}:slot:{i}"] = slot["prose"]
        for j, mark in enumerate(section.get("marks", [])):
            if mark.get("line"):
                out[f"{sid}:mark:{j}"] = mark["line"]
            for key, value in sorted((mark.get("detail") or {}).items()):
                if isinstance(value, str) and value:
                    out[f"{sid}:mark:{j}:{key}"] = value
    return out


def gate_lane(lane: str, texts: dict[str, str], pursuit, log, store,
              *outputs, agent: str = "writeback") -> EgressReport:
    """One call for a write-back lane: resolve the store, scan, record
    the line, and on a residue remove the lane's EARLIER outputs before
    re-raising (P2-56: a file no proof stands behind never outlives the
    refusal of the text it was made from)."""
    workspace = pursuit.root.parent
    try:
        return gate_egress(
            lane, texts,
            egress_identifiers(workspace, pursuit, store_for(workspace, store)),
            log, agent=agent)
    except EgressResidue:
        for path in outputs:
            Path(path).unlink(missing_ok=True)
        raise


def gate_egress(lane: str, texts: dict[str, str], identifiers: set[str],
                log, *, agent: str) -> EgressReport:
    """Scan, record the line, refuse typed on a blocking residue. The
    caller has not written anything yet — the refusal leaves no file."""
    report = scan_egress(lane, texts, identifiers)
    emit_scan(log, report, agent=agent)
    if not report.passed:
        raise EgressResidue(residue_message(report))
    return report
