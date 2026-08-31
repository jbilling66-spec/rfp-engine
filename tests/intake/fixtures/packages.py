"""Intake test packages: ground truth + the scripted intake_analyst.

The scripted wire is DERIVED from the prompt (the corpus.py pattern): the
fake regex-locates the S1 buyer frames and the lead-context block, then
builds its answer from what is actually present. Fixture, prompt, and
script cannot drift — and the clean and injected PDF runs produce the same
wire EXCEPT the injection flag, because everything else derives from
content both variants share.

HAND_WEIGHTS is the hand-extraction golden the acceptance clause compares
against: transcribed by reading the committed twins directly, not by
running the pipeline.
"""

import json
import re
from pathlib import Path

from engine.intake.brief import IntakeDoc, IntakePackage, run_intake
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.workspace import PursuitDir
from tests.fixtures.intake_twins import INJECTION_SENTENCE

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

PACKAGES: dict[str, list[tuple[str, str]]] = {
    "xlsx": [("structured-twin.xlsx", "rfp_main")],
    "pdf": [("pdf-twin.pdf", "rfp_main")],
    "pdf_injected": [("pdf-twin-injected.pdf", "rfp_main")],
    "hidden": [("hidden-twin.xlsx", "rfp_main")],
    "nofill": [("nofill-twin.xlsx", "rfp_main")],
    "gapcase": [("gapcase-twin.xlsx", "rfp_main")],
}

# Hand-extraction goldens (verbatim + basis, B17). xlsx: the merged D2:D4
# criterion "Technical capability (30%)" covers rows 2-4 → refs 2.0.1 and
# BOTH duplicate 2.0.5 rows; 2.0.7 (row 5) is outside the merge. pdf: the
# Section 4 table.
HAND_WEIGHTS = {
    "xlsx": [("2.0.1", 30.0, "percent"), ("2.0.5", 30.0, "percent"),
             ("2.0.5", 30.0, "percent")],
    "pdf": [("Technical approach", 40.0, "percent"),
            ("Implementation team", 25.0, "percent"),
            ("Past performance", 20.0, "percent"),
            ("Price", 15.0, "percent")],
}

RAMBLE = (
    "Quick context from me before you read the package: we have history "
    "here — the incumbent is Summit Apex Consulting and Northwind is openly "
    "unhappy with their change management. One hard constraint from the "
    "partner: no onsite staffing before March, travel budget is frozen "
    "until the new fiscal year."
)

_FRAME_RX = re.compile(
    r'<buyer_document source="([^"]+)" label="untrusted">\n(.*?)\n</buyer_document>',
    re.S,
)
_LEAD_RX = re.compile(
    r'<pursuit_lead_context label="firm">\n(.*?)\n</pursuit_lead_context>', re.S
)


def _page_of(source: str, content: str, pos: int) -> str:
    marker = None
    for match in re.finditer(r"\[page (\d+)\]", content[:pos]):
        marker = match.group(1)
    return f"{source} p{marker}" if marker else source


def _line_at(content: str, pos: int) -> str:
    start = content.rfind("\n", 0, pos) + 1
    end = content.find("\n", pos)
    return content[start : end if end != -1 else len(content)].strip()


def _derive_xlsx(source: str, content: str, wire: dict) -> None:
    if "Northwind Regional Health" in content:
        wire["buyer"].setdefault("name", "Northwind Regional Health")
        wire["buyer"].setdefault("vertical", "healthcare")
        wire["buyer"].setdefault(
            "profile", "Regional health system buying ERP implementation services."
        )
    if "ERP Implementation Services" in content:
        wire["procurement"].setdefault("what_is_bought", "ERP implementation services")
    wire["procurement"].setdefault("response_structure", "designated")
    for block in content.split("## Sheet: "):
        sheet_weighted = "(30%)" in block
        for match in re.finditer(r"\| (\d+\.\d+\.\d+) \| ([^|]+?) \|", block):
            ref, question = match.group(1), match.group(2).strip()
            row = {"ref": ref, "requirement": question}
            if sheet_weighted and ref in ("2.0.1", "2.0.5"):
                row["section"] = "Technical capability"
                row["weight_text"] = "30%"
            wire["requirements"].append(row)
        for match in re.finditer(r"\| (Q-\d) \| ([^|]+?) \|", block):
            wire["requirements"].append(
                {"ref": match.group(1), "requirement": match.group(2).strip()}
            )
        # Two-part refs (the nofill twin's 1.1-style numbering). Cannot
        # overlap the three-part branch: after "1.0" the next char in a
        # three-part ref is ".", never " |".
        for match in re.finditer(r"\| (\d+\.\d+) \| ([^|]+?) \|", block):
            wire["requirements"].append(
                {"ref": match.group(1), "requirement": match.group(2).strip()}
            )


def _derive_pdf(source: str, content: str, wire: dict) -> None:
    if "Northwind Regional Health" in content:
        wire["buyer"].setdefault("name", "Northwind Regional Health")
        wire["buyer"].setdefault("vertical", "healthcare")
        wire["buyer"].setdefault(
            "profile", "Regional health system buying ERP implementation services."
        )
    if "implement an integrated ERP platform" in content:
        wire["procurement"].setdefault(
            "what_is_bought",
            "ERP implementation services (finance, supply chain, human capital management)",
        )
        # buyer's own terms to mirror (left-hand rule)
        wire["buyer"].setdefault(
            "terminology",
            [t for t in ("integrated ERP platform", "human capital management")
             if t in content],
        )
    wire["procurement"].setdefault("response_structure", "free_flow")
    if "Northwind procurement portal" in content:
        wire["procurement"].setdefault("submission_method", "Northwind procurement portal")
    forms = re.findall(r"Form [A-Z] \([^)]+\)", content)
    if forms:
        wire["procurement"].setdefault("required_forms", forms)
    deadlines = []
    match = re.search(r"Written questions must be submitted by ([A-Z]\w+ \d{1,2}, \d{4})", content)
    if match:
        deadlines.append({"label": "Written questions due", "date_text": match.group(1)})
    match = re.search(r"Proposals are due no later than ([A-Z]\w+ \d{1,2}, \d{4} at [^.\n]+)", content)
    if match:
        deadlines.append({"label": "Proposal due", "date_text": match.group(1).strip()})
    if deadlines:
        wire["procurement"].setdefault("deadlines", deadlines)
    for match in re.finditer(
        r"(Technical approach|Implementation team|Past performance|Price): (\d{1,3})%", content
    ):
        wire["requirements"].append({
            "requirement": match.group(1),
            "section": "Evaluation Criteria",
            "weight_text": f"{match.group(2)}%",
        })
    for match in re.finditer(r"(3\.\d) (Vendor shall [^\n]+?\.)", content):
        wire["requirements"].append({
            "ref": match.group(1),
            "requirement": match.group(2),
            "section": "Scope of Services",
            "mandatory": True,
        })
    for needle, kind, detail in [
        ("generative AI", "ai_use", "AI-use disclosure and originality-of-work clause"),
        ("organizational conflict of interest", "independence_oci",
         "OCI certification clause"),
        (INJECTION_SENTENCE, "injection",
         "instruction-shaped text aimed at an AI system"),
    ]:
        pos = content.find(needle)
        if pos >= 0:
            wire["red_flags"].append({
                "kind": kind,
                "detail": detail,
                "excerpt": _line_at(content, pos),
                "source_location": _page_of(source, content, pos),
            })


def _wire_from_prompt(prompt: str) -> str:
    wire: dict = {"buyer": {}, "procurement": {}, "requirements": [], "red_flags": []}
    for source, content in _FRAME_RX.findall(prompt):
        if source.endswith(".xlsx"):
            _derive_xlsx(source, content, wire)
        else:
            _derive_pdf(source, content, wire)
    lead = _LEAD_RX.search(prompt)
    if lead:
        text = lead.group(1)
        if "Summit Apex Consulting" in text:
            wire["buyer"]["incumbent"] = "Summit Apex Consulting"
        if "no onsite staffing before March" in text:
            wire["buyer"]["profile"] = (
                wire["buyer"].get("profile", "")
                + " Pursuit-lead constraint: no onsite staffing before March."
            ).strip()
    return json.dumps(wire)


SCRIPT = {"intake_analyst": _wire_from_prompt}


def make_package(package_id: str, ramble: str | None = None) -> IntakePackage:
    return IntakePackage(
        pursuit_id=f"pur_{package_id}",
        docs=[IntakeDoc(path=FIXTURES / name, kind=kind)
              for name, kind in PACKAGES[package_id]],
        ramble=ramble,
    )


def run_package(tmp_root, package_id: str, *, ramble: str | None = None,
                script=None, package: IntakePackage | None = None,
                extraction=None):
    """Deterministic scripted intake run — the shared setup for the P3
    acceptance tests and the intake CLI's offline path. `extraction` is
    the C9 backend seam (tests pass FakeExtractionBackend)."""
    package = package or make_package(package_id, ramble)
    pursuit = PursuitDir(tmp_root, package.pursuit_id)
    log = RunLogger(pursuit.root, pursuit.new_run_id(), package.pursuit_id)
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot="kb@empty")
    report = run_intake(pursuit, caller, log, package, extraction=extraction)
    log.run_end(status="completed")
    return pursuit, report
