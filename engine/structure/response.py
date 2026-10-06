"""Layer 3 for COMPLETED response workbooks (P33a, B151): the buyer's
questionnaire with the firm's answers typed into the response column —
pair each question with the answer beside it, so the knowledge base can be
distilled from what the firm actually sent.

The vacancy parser (classify.py, `parse_workbook`) answers "where can an
answer GO" and is byte-pinned; this module answers "what was SAID" and
carries its own version constant, the DOCX_PARSER_VERSION precedent.
Layer 1 (facts.py) is reused as it is. Layer 2 (conventions.py) is a
named FALLBACK only: on a filled sheet its votes misread the file — the
writable-fill vote dies, the question column ties with the answer column
and flips when a question is short and its answer long, every short
question beside a short answer is a "label row", a filled ref-less
`Question | Response` sheet is a "grid" (B151 §3a). So the header scan,
the leaf depth and the row rules live here, and `sc.label_rows`,
`sc.kind` and `answer_cells` are never read.

Warnings carry addresses and kinds, never a cell's text (P1-23's law):
`"<sheet>!row N: <kind>"` for a row, `"<sheet>: <kind>"` for a sheet.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from engine.structure.classify import _field_type
from engine.structure.conventions import (
    depth,
    is_instructions,
    learn_conventions,
    merged_member_cols_by_row,
    row_ref,
)
from engine.structure.facts import CellFact, SheetFacts, collect_workbook_facts
from engine.structure.zipguard import ZipGuardError

# Bumped whenever the pairing rules change. Independent of PARSER_VERSION
# (the vacancy parser's pinned bytes never move for this module).
RESPONSE_PARSER_VERSION = "1.1.0"  # 1.1.0 (P33b): nothing answered -> every question row unanswered

HEADER_SCAN_ROWS = 10  # the header is found in the first rows, not voted

_QUESTION_LABEL = re.compile(
    r"\b(question|requirement|criteri\w*|description|item)\b", re.IGNORECASE)
_ANSWER_LABEL = re.compile(
    r"\b(response|answer|reply|comments?)\b", re.IGNORECASE)
# A later row made only of header words is the header repeated (a long
# sheet re-labelling itself), never a pair.
_HEADER_WORD = re.compile(
    r"^(ref\.?|#|no\.?|id|item|section|question|requirement|criteri\w*|"
    r"description|response|answer|reply|comments?)$", re.IGNORECASE)
# An answer that is a number, a currency or a percentage — never prose,
# never corpus (the P3-1 posture: a fee rides into no card).
_NON_PROSE = re.compile(
    r"^[\s$€£]*[-+]?[\d][\d.,]*\s*(%|k|mm|m|bn)?[\s$€£]*$", re.IGNORECASE)
_BARE_ANSWERS = frozenset({"yes", "no", "y", "n", "n/a", "na", "none", "tbd",
                           "not applicable", "see attached", "see appendix"})


class ResponseWorkbookError(ValueError):
    """The file is not a readable workbook. One typed refusal for the door."""


@dataclass(frozen=True)
class Pair:
    row: int
    question: str  # one line — never reaches a card body
    answer: str
    ref: str | None = None


@dataclass
class ResponseSection:
    heading: str | None
    pairs: list[Pair] = field(default_factory=list)


@dataclass
class ResponseSheet:
    name: str  # BYTE-EXACT, as Layer 1 keeps it
    sections: list[ResponseSection] = field(default_factory=list)

    def pairs(self) -> list[Pair]:
        return [p for s in self.sections for p in s.pairs]


@dataclass
class ResponseWorkbook:
    file: str
    parser_version: str
    source_sha256: str
    sheets: list[ResponseSheet] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)

    def pairs(self) -> list[Pair]:
        return [p for s in self.sheets for p in s.pairs()]

    def to_dict(self) -> dict:
        """Writers omit: no `None`, sorted skip counts — the shape tests
        compare across directories."""
        raw = dataclasses.asdict(self)
        raw["skipped"] = dict(sorted(raw["skipped"].items()))
        return _omit_none(raw)


def _omit_none(value):
    if isinstance(value, dict):
        return {k: _omit_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_omit_none(v) for v in value]
    return value


# ---- the door --------------------------------------------------------------

def pair_response_workbook(path: Path) -> ResponseWorkbook:
    path = Path(path)
    if not path.is_file():
        raise ResponseWorkbookError(f"no workbook at {path}")
    try:
        facts = collect_workbook_facts(path)
    except (ZipGuardError, InvalidFileException, BadZipFile, KeyError) as exc:
        raise ResponseWorkbookError(
            f"{path.name}: not a readable workbook ({type(exc).__name__})"
        ) from exc
    conv = learn_conventions(facts)
    book = ResponseWorkbook(
        file=path.name,
        parser_version=RESPONSE_PARSER_VERSION,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    for sheet in facts.sheets:
        if is_instructions(sheet):
            _skip(book, "instructions sheets")
            continue
        if sheet.hidden:
            _skip(book, "hidden sheets", f"{sheet.name.strip()}: hidden sheet skipped")
            continue
        sc = conv.sheets[sheet.name]
        parsed = _pair_sheet(sheet, sc.ref_col, sc.question_col, sc.answer_col,
                             sc.first_label_row, book)
        if parsed is not None and parsed.pairs():
            book.sheets.append(parsed)
    return book


def _skip(book: ResponseWorkbook, kind: str, warning: str | None = None) -> None:
    book.skipped[kind] = book.skipped.get(kind, 0) + 1
    if warning is not None:
        book.warnings.append(warning)


# ---- one sheet ---------------------------------------------------------------

def _pair_sheet(sheet: SheetFacts, ref_col: int | None, fallback_q: int | None,
                fallback_a: int | None, fallback_header: int | None,
                book: ResponseWorkbook) -> ResponseSheet | None:
    name = sheet.name.strip()
    rows = sheet.rows()
    header_row, q_col, a_col, a_label = _find_header(rows, ref_col)
    if header_row is None:
        q_col, a_col = fallback_q, fallback_a
        if q_col is None or a_col is None or q_col == a_col:
            _skip(book, "sheets without columns",
                  f"{name}: no question/answer columns, sheet skipped")
            return None
        # Layer 2's label row is the header here, or there is none
        header_row = fallback_header or 0
        book.warnings.append(f"{name}: columns inferred, no header row found")
    elif _field_type(a_label) != "text":
        _skip(book, "pricing-shaped sheets", f"{name}: pricing-shaped sheet skipped")
        return None
    if a_col in sheet.hidden_cols:
        _skip(book, "hidden answer columns",
              f"{name}: hidden answer column, sheet skipped")
        return None

    members = merged_member_cols_by_row(sheet)

    def answer_fact(row_num: int, row_facts: list[CellFact]) -> CellFact | None:
        if a_col in members.get(row_num, set()):
            return None  # a merged-range member belongs to its anchor
        return next((f for f in row_facts if f.col == a_col), None)

    # Leaf depth from the rows that ARE answered — never a vacancy vote.
    depths: Counter[int] = Counter()
    for row_num, row_facts in rows.items():
        if row_num <= header_row:
            continue
        ref = row_ref(row_facts, ref_col)
        fact = answer_fact(row_num, row_facts)
        if ref and fact is not None and _answer_text(fact) is not None:
            depths[depth(ref)] += 1
    if depths:
        leaf_depth = max(depths.items(), key=lambda kv: (kv[1], kv[0]))[0]
    else:
        # 1.1.0 (P33b, B154 §4): nothing answered means no leaf to vote.
        # Layer 2's default depth made every shallow ref row a silent
        # heading, so a workbook nobody answered refused with no
        # address at all. No leaves -> no headings -> every question
        # row is `unanswered`, said by address.
        leaf_depth = 0

    out = ResponseSheet(name=sheet.name, sections=[ResponseSection(heading=None)])
    non_prose_here = 0
    for row_num, row_facts in sorted(rows.items()):
        if row_num <= header_row:
            continue  # titles and the header itself
        if row_num in sheet.hidden_rows:
            _skip(book, "hidden rows", f"{name}!row {row_num}: hidden row skipped")
            continue
        if _is_repeated_header(row_facts, ref_col):
            _skip(book, "repeated headers",
                  f"{name}!row {row_num}: repeated header row skipped")
            continue
        ref = row_ref(row_facts, ref_col)
        q_fact = next((f for f in row_facts if f.col == q_col), None)
        if q_fact is not None and q_fact.is_formula and q_fact.cached_text is None:
            _skip(book, "formula questions without cache",
                  f"{name}!row {row_num}: formula question without cached value skipped")
            continue
        question = _one_line(q_fact.text) if q_fact is not None else None
        a_fact = answer_fact(row_num, row_facts)
        if a_fact is not None and a_fact.is_formula and a_fact.cached_text is None:
            _skip(book, "formula answers without cache",
                  f"{name}!row {row_num}: formula answer without cached value skipped")
            continue
        answer = _answer_text(a_fact) if a_fact is not None else None

        if ref and depth(ref) < leaf_depth and answer is None:
            out.sections.append(ResponseSection(heading=question or ref))
            continue
        if question and answer:
            if _non_prose(answer):
                non_prose_here += 1
                _skip(book, "non-prose answers",
                      f"{name}!row {row_num}: non-prose answer skipped")
                continue
            out.sections[-1].pairs.append(
                Pair(row=row_num, ref=ref, question=question, answer=answer))
            continue
        if question and answer is None:
            _skip(book, "unanswered", f"{name}!row {row_num}: unanswered")
            continue
        if answer and not question:
            _skip(book, "orphan answers", f"{name}!row {row_num}: orphan answer")
            continue
        # neither a question nor an answer: furniture, silent (as classify.py)

    out.sections = [s for s in out.sections if s.pairs]
    if not out.sections and non_prose_here:
        _skip(book, "pricing-shaped sheets", f"{name}: pricing-shaped sheet skipped")
        return None
    return out


# ---- the small rules -------------------------------------------------------------

def _find_header(rows: dict[int, list[CellFact]], ref_col: int | None
                 ) -> tuple[int | None, int | None, int | None, str]:
    """The first row (before the first ref-carrying row, within the top
    HEADER_SCAN_ROWS) holding one cell that names the question column and a
    DIFFERENT cell that names the answer column. No length cap — a real
    header reads "Vendor Response (max 200 words; do not alter formatting)"."""
    for row_num, row_facts in sorted(rows.items())[:HEADER_SCAN_ROWS]:
        if row_ref(row_facts, ref_col) is not None:
            break
        labels = [(f.col, f.text.strip()) for f in row_facts
                  if f.text and not f.is_formula]
        a_cols = [(c, t) for c, t in labels if _ANSWER_LABEL.search(t)]
        q_cols = [c for c, t in labels
                  if _QUESTION_LABEL.search(t) and c not in {ac for ac, _ in a_cols}]
        if not a_cols or not q_cols:
            # a cell may name both ("Response to requirement"): the first
            # question-naming cell that is not the chosen answer cell
            q_only = [c for c, t in labels if _QUESTION_LABEL.search(t)]
            a_only = [(c, t) for c, t in labels if _ANSWER_LABEL.search(t)]
            if len(q_only) >= 1 and len(a_only) >= 1:
                a_col, a_label = next(
                    ((c, t) for c, t in a_only if c not in q_only), a_only[-1])
                q_col = next((c for c in q_only if c != a_col), None)
                if q_col is not None:
                    return row_num, q_col, a_col, a_label
            continue
        a_col, a_label = a_cols[0]
        return row_num, q_cols[0], a_col, a_label
    return None, None, None, ""


def _is_repeated_header(row_facts: list[CellFact], ref_col: int | None) -> bool:
    texts = [f.text.strip() for f in row_facts if f.text and not f.is_formula]
    if len(texts) < 2 or row_ref(row_facts, ref_col) is not None:
        return False
    return all(_HEADER_WORD.match(t) for t in texts)


def _one_line(text: str | None) -> str | None:
    """A question is ONE line: a cell's newlines would otherwise put
    question text into the card body (the owner's call, B151 §1c)."""
    if text is None:
        return None
    joined = " ".join(text.split())
    return joined or None


def _answer_text(fact: CellFact) -> str | None:
    """The answer keeps its own line breaks; a formula answer is its cached
    value (Layer 1 put the cache in `text`) or nothing."""
    if fact.text is None:
        return None
    if fact.is_formula and fact.cached_text is None:
        return None
    lines = [line.rstrip() for line in fact.text.splitlines()]
    joined = "\n".join(lines).strip()
    return joined or None


def _non_prose(answer: str) -> bool:
    stripped = answer.strip().strip(".").strip().lower()
    return bool(_NON_PROSE.match(answer)) or stripped in _BARE_ANSWERS
