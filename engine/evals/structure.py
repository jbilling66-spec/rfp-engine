"""Structure Parser component suite (EVAL_SUITE Tier-1 row).

Deterministic and model-free: the parser is pure code, so exact-match
against a hand-transcribed golden is the right scoring method and the
numbers are reproducible from the repo alone.

Two halves:
  * the committed twins (tests/fixtures/*.xlsx) — the shapes the engine
    already handles, pinned so a parser change cannot move them quietly;
  * three ADVERSARIAL structures, built here in code rather than
    committed as binaries. A generated workbook keeps the suite readable
    (the adversarial trait is a line of Python, not an opaque cell), and
    keeps the tripwire's extraction sweep free of new binaries (B40/D21).

Each adversarial case names the trait it attacks, because a suite whose
cases are unexplained cannot tell you what broke when it fails:
  A1 leading banner rows   — the header is not row 1.
  A2 merged question cells — the prompt spans a merged range.
  A3 blank spacer rows     — answer rows are not contiguous.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"

# Transcribed by reading the committed twins directly (house golden rule),
# and matching the counts tests/structure/test_structure_parse.py already
# carries. Only the Path-A designated-structure twins belong here:
# hidden-twin.xlsx is an INTAKE screening fixture (hidden sheet carrying a
# planted injection) with no answer column, so it is not a structure case
# and scoring it as one would manufacture a failure the parser never had.
TWIN_GOLDENS = {
    "demo-twin.xlsx": {"slot_count": 19, "source_mode": "client_provided"},
    "structured-twin.xlsx": {"slot_count": 8, "source_mode": "client_provided"},
    "gapcase-twin.xlsx": {"slot_count": 4, "source_mode": "client_provided"},
    "nofill-twin.xlsx": {"slot_count": 4, "source_mode": "client_provided"},
}

ADVERSARIAL_GOLDENS = {
    "adv_banner_rows": 3,
    "adv_merged_prompt": 3,
    "adv_blank_spacers": 3,
}

# P2-36 (P26b-3): the floor is the committed case count (4 twins + 3
# adversarial shapes).
MINIMUM_N = {"cases": 7}


def _write_workbook(path: Path, rows, *, merges=()):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "1. Response"
    for row in rows:
        sheet.append(row)
    for span in merges:
        sheet.merge_cells(span)
    book.save(path)
    return path


def build_adversarial(workdir: Path) -> dict[str, Path]:
    """The three adversarial structures, generated deterministically."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    built = {}

    # A1 — two banner rows above the real header.
    built["adv_banner_rows"] = _write_workbook(
        workdir / "adv_banner_rows.xlsx",
        [["REQUEST FOR PROPOSAL — RESPONSE FORM", None, None],
         ["Return by 2026-09-30", None, None],
         ["Ref", "Question", "Response"],
         ["2.1", "Describe your implementation methodology.", None],
         ["2.2", "Describe your data migration approach.", None],
         ["2.3", "Describe your training approach.", None]])

    # A2 — the prompt text lives in a merged range.
    built["adv_merged_prompt"] = _write_workbook(
        workdir / "adv_merged_prompt.xlsx",
        [["Ref", "Question", "Response"],
         ["3.1", "Describe your governance and escalation structure.", None],
         ["3.2", "Describe your risk management approach.", None],
         ["3.3", "Describe your reporting and analytics approach.", None]],
        merges=("B2:C2",))

    # A3 — blank spacer rows between answer rows.
    built["adv_blank_spacers"] = _write_workbook(
        workdir / "adv_blank_spacers.xlsx",
        [["Ref", "Question", "Response"],
         ["4.1", "Describe your payroll parallel testing approach.", None],
         [None, None, None],
         ["4.2", "Describe your interface testing approach.", None],
         [None, None, None],
         ["4.3", "Describe your hypercare support model.", None]])
    return built


def evaluate_structure_set(workdir: Path) -> dict:
    """Exact-match over both halves. A case that RAISES is a failure with
    its exception recorded — a parser that crashes on an adversarial
    shape has told us something, and it must not read as a silent skip."""
    from engine.evals.cases import rate
    from engine.structure import PARSER_VERSION, parse_workbook

    cases = 0
    matched = 0
    failures: list[str] = []

    for name, golden in sorted(TWIN_GOLDENS.items()):
        cases += 1
        try:
            parsed = parse_workbook(FIXTURES / name)
        except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
            failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
            continue
        if (parsed.slot_count == golden["slot_count"]
                and parsed.source_mode == golden["source_mode"]):
            matched += 1
        else:
            failures.append(
                f"{name}: {parsed.slot_count} slots / {parsed.source_mode} "
                f"!= golden {golden['slot_count']} / {golden['source_mode']}")

    for name, path in sorted(build_adversarial(workdir).items()):
        cases += 1
        expected = ADVERSARIAL_GOLDENS[name]
        try:
            parsed = parse_workbook(path)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
            continue
        if parsed.slot_count == expected:
            matched += 1
        else:
            failures.append(f"{name}: {parsed.slot_count} slots "
                            f"!= golden {expected}")

    return {
        "suite": "structure_parse",
        "parser_version": PARSER_VERSION,
        "n_cases": cases,
        "exact_match": rate(matched, cases, floor=MINIMUM_N["cases"],
                            lane="structure", of="golden cases"),
        "minimum_n": dict(MINIMUM_N),
        "failures": sorted(failures),
    }
