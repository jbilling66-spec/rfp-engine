"""Shared research-test fixtures: frame regexes, hand-transcribed pack
goldens, the derive-wire-from-prompt scripts for BOTH researchers, and the
run harness.

The scripted wires are DERIVED from the prompt (the packages.py pattern):
the internal fake reads back the kb_card frames code actually inlined, the
external fake reads back the pack sections inside the research frame —
fixture, prompt, frame, and script cannot drift. The frame regexes are the
single source the frame-drift tripwire (test_research_frames) and these
scripts key on — if a frame's shape changes, both fail together, never
silently apart."""

import json
import re
from pathlib import Path

from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.research import run_research
from engine.runlog import RunLogger
from engine.version import engine_version
from tests.intake.fixtures.packages import RAMBLE, run_package
from tests.kb.fixtures.corpus import ingest_corpus

_RESEARCH_FRAME_RX = (r'<research_document source="([^"]+)" label="untrusted">\n'
                      r"(.*?)\n</research_document>")
_KB_CARD_RX = (r'<kb_card kb_id="([^"]+)" title="([^"]*)" label="firm">\n'
               r"(.*?)\n</kb_card>")

PACK_PATH = Path(__file__).resolve().parent / "research-pack.md"

# Hand-transcribed goldens from research-pack.md (never derived by the code
# under test): heading -> (source URL, unique marker phrase in the body).
PACK_TITLE = "regional health system ERP pursuit"
PACK_SECTIONS = {
    "Buyer strategic context": (
        "https://example.org/synthetic/strategy-brief",
        "multi-year clinical systems modernization program",
    ),
    "Vendor landscape and incumbent signals": (
        "https://example.org/synthetic/vendor-landscape",
        "advisory incumbent has held the account since 2022",
    ),
    "Procurement and financial signals": (
        "https://example.org/synthetic/financial-signals",
        "capital budget review cycle concludes each June",
    ),
}

# Deal-identifying tokens planted in the P3 buyer package (docs + ramble).
# test_query_hygiene proves each one IS present in the buyer-facing inputs
# (non-vacuous) and then that NONE appears anywhere in the research run log.
PLANTED_BUYER_TOKENS = [
    "Northwind",
    "Summit Apex",
    "implement an integrated ERP platform",
]

# Golden topic list for the pdf-twin pursuit (hand-derived from TOPIC_VOCAB
# against vertical=healthcare + the ERP what-is-bought text).
EXPECTED_TOPICS = [
    "regional health system strategic priorities",
    "health system back-office modernization trends",
    "ERP implementation delivery approaches",
    "ERP program vendor landscape and incumbent dynamics",
    "implementation services procurement and budgeting practices",
]

_TOPICS_RX = re.compile(r"Abstracted research topics:\n((?:- [^\n]+\n?)+)")
_MODE_RX = re.compile(r"Research mode for this run: (\w+)\.")
_PACK_SECTION_RX = re.compile(r"## ([^\n]+)\n+source: (\S+)\n(.*?)(?=\n## |\Z)", re.S)


def _topics_of(prompt: str) -> list[str]:
    block = _TOPICS_RX.search(prompt).group(1)
    return [line[2:].strip() for line in block.strip().splitlines()]


def _internal_wire(prompt: str) -> str:
    topics = _topics_of(prompt)
    findings = []
    for kb_id, title, body in re.findall(_KB_CARD_RX, prompt, re.S):
        first_line = body.strip().splitlines()[0].strip()
        findings.append({
            "claim": f"Firm precedent: {first_line}",
            "detail": title,
            "kb_id": kb_id,
            "topic": topics[0],
        })
    return json.dumps({"findings": findings})


def _external_wire(prompt: str) -> str:
    topics = _topics_of(prompt)
    mode = _MODE_RX.search(prompt).group(1)
    frame = re.search(_RESEARCH_FRAME_RX, prompt, re.S)
    findings = []
    if frame:
        for heading, url, body in _PACK_SECTION_RX.findall(frame.group(2)):
            first_sentence = body.strip().replace("\n", " ").split(". ")[0]
            findings.append({
                "claim": first_sentence.rstrip(".") + ".",
                "detail": heading,
                "source_url": url,
                "topic": topics[0],
            })
    elif mode in ("full_web", "allowlist"):
        findings.append({
            "claim": "Synthetic web finding for smoke coverage.",
            "source_url": f"https://example.org/synthetic/{mode}-result",
            "topic": topics[0],
        })
    return json.dumps({"findings": findings})


SCRIPT = {
    "internal_researcher": _internal_wire,
    "external_researcher": _external_wire,
}


def run_research_package(tmp_root, *, research_yaml=None, script=None,
                         pack: bool = True, package_id: str = "pdf"):
    """P3 intake run (run_0001, brief written) → corpus KB → research run
    (run_0002). Returns (pursuit, research report)."""
    pursuit, _ = run_package(tmp_root, package_id, ramble=RAMBLE)
    store, _ = ingest_corpus(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    cfg = (effective_config(research_yaml=research_yaml) if research_yaml
           else effective_config())
    mode = cfg["research_mode"]
    log.run_start(mode="dry_run", engine_version=engine_version(), config=cfg,
                  kb_snapshot=store.snapshot(), research_mode=mode)
    pack_path = None
    if pack:
        pack_path = pursuit.root / "inbox" / "research-pack.md"
        pack_path.write_bytes(PACK_PATH.read_bytes())
    report = run_research(pursuit, caller, log, store, mode=mode, pack=pack_path)
    log.run_end(status="completed")
    return pursuit, report
