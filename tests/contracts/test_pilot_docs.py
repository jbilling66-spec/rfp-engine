"""P21 acceptance — docs/pilot/ agrees with the doors and laws it states (B83).

The operator kit is prose, so the checks are containment, one direction —
the artifact-flow precedent (B79 D3; B83 section 2): every door reference
written in canonical backticked form resolves to a doors.md row; every
security-law anchor clause appears verbatim (whitespace-normalized) in BOTH
its authoritative home and the pilot doc that states the law; the answering
doc's contract values are introspected from engine.llm.handoff and the
argparse tree, never copied. Each doc's preamble states exactly the
guarantee enforced here, and that sentence is itself asserted, so a doc
cannot outclaim its test (lessons.md line 11). Prose mentions, fenced
blocks, and abbreviated forms escape the containment sweeps by construction
— the docs' writing conventions exist so that they are not used. A red
names the reference or clause that moved: fix the code or the home first,
then the sentence the red names.
"""

import argparse
import dataclasses
import re
from pathlib import Path

from engine.cli.main import build_parser
from engine.llm.handoff import PROTOCOL, _SEQ_RX, HandoffCaller

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "docs" / "pilot"
DOORS = REPO / "docs" / "graph" / "doors.md"

DOC_NAMES = (
    "operator-guide.md",
    "runbook.md",
    "answering-session.md",
    "operator-CLAUDE.md",
)

# Each doc claims exactly what this file enforces for it, in its preamble.
_GUARANTEES = {
    "operator-guide.md": (
        "every bold phrase in this guide appears verbatim in the web app's "
        "source files — that is what the drift test checks, and no more"),
    "runbook.md": (
        "Every backticked door reference in canonical form resolves to a "
        "row of the door index — that is what the drift test checks, and "
        "no more"),
    "answering-session.md": (
        "The protocol string, field names, filenames, and defaults stated "
        "here are checked against the handoff caller's own source — that "
        "is what the drift test checks, and no more"),
    "operator-CLAUDE.md": (
        "Every backticked door reference in canonical form resolves to a "
        "row of the door index — that is what the drift test checks, and "
        "no more"),
}

# Anchor clauses: short on purpose (full lines red on every legitimate
# home-file append), each required verbatim-normalized in BOTH the law's
# authoritative home and the pilot doc that states it (B83 D5). All five
# doc-homed laws anchor in CLAUDE.md since B85 D2: the paraphrase and
# read-and-run laws re-homed there (standing rules 6-7) so every home is
# a file the public mirror ships — lessons.md and ROADMAP.md keep their
# copies, but the anchor binds the shipped home.
_LAWS = (
    ("Zero spend by default.", "CLAUDE.md", "runbook.md"),
    ("Synthetic data only, until A1.", "CLAUDE.md", "operator-guide.md"),
    ("No real client names, fees, people, or documents anywhere",
     "CLAUDE.md", "operator-guide.md"),
    ("Document a forbidden token by paraphrase, never by reproducing it",
     "CLAUDE.md", "operator-CLAUDE.md"),
    ("no engine code is ever edited on the work side",
     "CLAUDE.md", "runbook.md"),
    ("no engine code is ever edited on the work side",
     "CLAUDE.md", "operator-CLAUDE.md"),
    ("a handoff call consumes an operator's seat, not an API key",
     "engine/llm/handoff.py", "answering-session.md"),
)

_ROUTE_RX = re.compile(r"`(GET|POST|PUT|DELETE|PATCH|HEAD) (/[^`]*)`")
_MAKE_RX = re.compile(r"`(?:[A-Z_]+=\S+ )*make ([A-Za-z][\w-]*)[^`]*`")
_CLI_RX = re.compile(
    r"`(?:caffeinate -i )?(?:\.venv/bin/python|python3?) -m "
    r"(engine(?:\.[\w.]+)*)((?: [^`]*)?)`")
_FLAG_RX = re.compile(r"`(--[a-z][a-z0-9-]*)`")


def _read(name):
    return (PILOT / name).read_text()


def _norm(s):
    # Whitespace-fold (handoff.py's docstring wraps its anchor mid-phrase),
    # apostrophe-fold (a smart-quote edit must not unpin a law), and
    # blockquote-fold (a `> ` continuation marker is presentation — an
    # anchor quoted across wrapped blockquote lines still binds).
    s = re.sub(r"^>\s?", "", s.replace("’", "'"), flags=re.M)
    return " ".join(s.split())


# Twin of tests/contracts/test_graph_doors.py's parser — doors.md's
# `method` header repeats across its subsections, so rows accumulate.
def _rows_with_header(header0):
    rows = []
    text = DOORS.read_text().splitlines()
    for i, line in enumerate(text):
        if line.startswith("|") and [c.strip() for c in line.strip("|").split("|")][0] == header0:
            for later in text[i + 1:]:
                if not later.startswith("|"):
                    break
                cells = [c.strip() for c in later.strip("|").split("|")]
                if all(set(c) <= {"-", " "} for c in cells):
                    continue
                rows.append(cells)
    assert rows, f"no table rows under a '{header0}' header in doors.md"
    return rows


def test_pilot_docs_exist_and_state_their_own_guarantee():
    for name in DOC_NAMES:
        path = PILOT / name
        assert path.is_file(), f"docs/pilot/{name} is missing"
        assert _norm(_GUARANTEES[name]) in _norm(_read(name)), (
            f"docs/pilot/{name} must state the guarantee this suite "
            f"enforces for it, verbatim (lessons.md line 11): "
            f"{_GUARANTEES[name]!r}")


def test_route_references_resolve_to_door_rows():
    doc_rows = {(r[0], r[1].strip("`")) for r in _rows_with_header("method")}
    found = []
    for name in DOC_NAMES:
        for method, path in _ROUTE_RX.findall(_read(name)):
            found.append((name, method, path))
            assert (method, path) in doc_rows, (
                f"docs/pilot/{name} cites `{method} {path}` but the door "
                f"index carries no such row")
    assert found, ("no canonical route reference found in any pilot doc — "
                   "either the docs or this regex rotted")


def test_make_references_resolve_to_door_rows():
    targets = {r[0].strip("`") for r in _rows_with_header("target")}
    found = []
    for name in DOC_NAMES:
        for target in _MAKE_RX.findall(_read(name)):
            found.append((name, target))
            assert target in targets, (
                f"docs/pilot/{name} cites `make {target}` but doors.md's "
                f"make table has no such target")
    assert found, ("no make-target reference found in any pilot doc — "
                   "either the docs or this regex rotted")


def _command_tokens(tail):
    toks = []
    for tok in tail.split():
        if tok[0] in "-<{…":
            break
        toks.append(tok)
    return toks


def test_cli_references_resolve_to_door_rows():
    cli_rows = [r[0].strip("`").split() for r in _rows_with_header("command")]
    module_rows = {r[0].strip("`"): r[1] for r in _rows_with_header("module")}
    found = []
    for name in DOC_NAMES:
        for module, tail in _CLI_RX.findall(_read(name)):
            found.append((name, module))
            if module != "engine":
                assert module in module_rows, (
                    f"docs/pilot/{name} cites `python -m {module}` but the "
                    f"door index's module table has no such row")
                assert not module_rows[module].startswith("Internal"), (
                    f"docs/pilot/{name} cites `python -m {module}` — "
                    f"doors.md marks it Internal, not an operator door")
                continue
            toks = _command_tokens(tail)
            ok = any(row[:len(toks)] == toks or toks[:len(row)] == row
                     for row in cli_rows)
            assert ok, (
                f"docs/pilot/{name} cites `python -m engine "
                f"{' '.join(toks)}` but no CLI-table row matches it")
    assert found, ("no CLI invocation found in any pilot doc — "
                   "either the docs or this regex rotted")


def _collect_options(parser, opts):
    for act in parser._actions:
        opts.update(act.option_strings)
        if isinstance(act, argparse._SubParsersAction):
            for sub in act.choices.values():
                _collect_options(sub, opts)


def test_flag_references_are_real_options():
    opts = set()
    _collect_options(build_parser(), opts)
    found = []
    for name in DOC_NAMES:
        for flag in sorted(set(_FLAG_RX.findall(_read(name)))):
            found.append((name, flag))
            assert flag in opts, (
                f"docs/pilot/{name} cites `{flag}` but no engine command "
                f"carries that option (the check is tree-wide, so a flag "
                f"cited against the wrong command still passes — the door "
                f"containment above carries the command itself)")
    assert found, ("no standalone flag reference found in any pilot doc — "
                   "either the docs or this regex rotted")


def test_security_law_anchors_bind_home_and_pilot_doc():
    for anchor, home, doc in _LAWS:
        home_text = _norm((REPO / home).read_text())
        assert _norm(anchor) in home_text, (
            f"the law's home moved: {home} no longer carries the anchor "
            f"{anchor!r} — re-anchor the law before touching the pilot doc")
        assert _norm(anchor) in _norm(_read(doc)), (
            f"docs/pilot/{doc} must state the law verbatim: {anchor!r} "
            f"(its home: {home})")


def test_answering_doc_matches_the_handoff_contract():
    doc = _read("answering-session.md")
    assert PROTOCOL in doc, (
        f"answering-session.md must name the protocol {PROTOCOL!r}")
    # Response fields from the caller's own source, never a copy: a field
    # rename in _accept reds here because the doc lacks the new name. (A
    # field REMOVAL is not caught — one direction, stated in the preamble.)
    src = (REPO / "engine" / "llm" / "handoff.py").read_text()
    fields = set(re.findall(r'payload\.get\("(\w+)"\)', src))
    assert fields, ("handoff.py no longer reads response fields via "
                    "payload.get — re-pin this test to the new idiom")
    for field in sorted(fields):
        assert f"`{field}`" in doc, (
            f"answering-session.md must name the response field `{field}` "
            f"(handoff.py reads it)")
    # The filename pattern, through the caller's own regex —
    for example in ("call-0001.request.json", "call-0001.response.json"):
        assert example in doc, (
            f"answering-session.md must show the example filename {example}")
        assert _SEQ_RX.match(example), (
            f"handoff.py's filename pattern no longer matches {example} — "
            f"the doc's examples rotted")


def _subparser(parser, name):
    act = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    return act.choices[name]


def _default(parser, option):
    return next(a for a in parser._actions
                if option in a.option_strings).default


def test_stated_defaults_equal_the_introspected_defaults():
    parser = build_parser()
    serve = _subparser(parser, "serve")
    slice_ = _subparser(parser, "slice")
    timeouts = {
        _default(serve, "--handoff-timeout"),
        _default(slice_, "--handoff-timeout"),
        next(f for f in dataclasses.fields(HandoffCaller)
             if f.name == "timeout").default,
    }
    assert len(timeouts) == 1, (
        f"the three handoff-timeout literals drifted apart: {timeouts}")
    stated = re.findall(r"default (\d+) seconds",
                        _read("answering-session.md"))
    assert len(stated) == 1, (
        "answering-session.md must state the wait exactly once, as "
        "'default N seconds'")
    assert float(stated[0]) == timeouts.pop()
    port = _default(serve, "--port")
    assert f"127.0.0.1:{port}" in _read("runbook.md"), (
        f"the runbook must state the workbench address as "
        f"127.0.0.1:{port} (serve's introspected --port default)")


def test_operator_guide_bold_spans_are_ui_text():
    ui = ((REPO / "engine" / "web" / "static" / "app.html").read_text()
          + (REPO / "engine" / "web" / "static" / "app.js").read_text())
    spans = re.findall(r"\*\*([^*\n]+)\*\*", _read("operator-guide.md"))
    assert spans, ("the operator guide names no on-screen text at all — "
                   "either the guide or this regex rotted")
    missing = sorted({s for s in spans if s not in ui})
    assert not missing, (
        "bold is reserved for on-screen text in the operator guide, and "
        f"these spans appear nowhere in the UI source: {missing}")
