"""Structure parsing (Path A): buyer workbook -> TargetSlots.

Three strict layers, reimplemented from the v1 oracle (the v1 repo's
engine/structure/, read-only): facts (facts.py — what IS in the file)
-> learned per-workbook conventions (conventions.py) -> classification
(classify.py, orchestrated by parse.py). Detectors never read the
workbook directly and never hardcode colors or cell addresses.
"""

# Bumped whenever classification rules change (the P10 unseen-twin
# contract keys on it). FROZEN through P16 (B73§4): the xlsx path is
# byte-pinned; the docx parsers version independently below.
PARSER_VERSION = "2.0.0"

# The docx parsers' own version (P16): bumping one never moves the
# other's pinned bytes.
DOCX_PARSER_VERSION = "1.0.0"

from engine.structure.parse import ParsedWorkbook, StructureError, parse_workbook  # noqa: E402
from engine.structure.docx_default import parse_default_template  # noqa: E402
from engine.structure.docx_buyer import parse_buyer_docx  # noqa: E402
from engine.structure.targets import (  # noqa: E402
    merge_parsed,
    parse_target,
    scan_core_document,
)

__all__ = ["PARSER_VERSION", "DOCX_PARSER_VERSION", "ParsedWorkbook",
           "StructureError", "parse_workbook", "parse_default_template",
           "parse_buyer_docx", "parse_target", "scan_core_document",
           "merge_parsed"]
