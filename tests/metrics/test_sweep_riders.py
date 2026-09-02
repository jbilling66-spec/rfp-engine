"""The session-36 sweep's metric riders (P26a Group E): production_only
keys by (pursuit, run) so one pursuit's bench run cannot drop another's
production series (P1-32); the fabrication count reads the filename-
keyed two_path record the writer produces (P1-33); injection flags count
FLAGS and are absent on an empty corpus (P1-34); cycle_time_days is
honestly unsourced (P2-42); the two bench absences carry their real
reason (P2-43); and requirement_coverage resolves from coverage lines
at section grain (P0-15)."""

import json
from pathlib import Path

from engine.metrics.resolver import Corpus, resolve
from engine.metrics.walker import production_only


def _run(ws, pid, run_id, mode, lines):
    root = ws / pid
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    records = [{"run_id": run_id, "pursuit_id": pid, "seq": 0,
                "ts": "2026-09-02T10:00:00Z", "record_type": "run_start",
                "run": {"mode": mode}}]
    for i, line in enumerate(lines, start=1):
        records.append({"run_id": run_id, "pursuit_id": pid, "seq": i,
                        "ts": "2026-09-02T10:00:01Z", **line})
    (run_dir / "run.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n")


def _coverage(result):
    return {"record_type": "validation",
            "validation": {"check": "coverage", "result": result}}


def _screen(result):
    return {"record_type": "validation",
            "validation": {"check": "injection_screen", "result": result}}


def test_production_only_keys_by_pursuit_and_run(tmp_path):
    ws = tmp_path / "ws"
    _run(ws, "pur_a", "run_0001", "live", [_coverage("pass")])
    _run(ws, "pur_b", "run_0001", "regression_bench", [_coverage("pass")])
    corpus = Corpus(ws)
    kept = corpus.runs()
    assert {r["pursuit_id"] for r in kept} == {"pur_a"}, \
        "pur_b's bench run_0001 must not evict pur_a's production run_0001"
    raw = [r for p in corpus.pursuits for r in p.runs]
    assert len(production_only(raw)) == len(kept) == 2


def test_requirement_coverage_is_section_grain_and_absent_never_zero(
        tmp_path):
    ws = tmp_path / "ws"
    _run(ws, "pur_a", "run_0001", "live",
         [_coverage("pass"), _coverage("pass"), _coverage("pass"),
          _coverage("flag")])
    row = resolve("requirement_coverage", Corpus(ws))
    assert row["status"] == "count_only" and row["value"] == 0.75
    assert row["n"] == 4
    _run(ws, "pur_c", "run_0001", "live", [_coverage("pass")] * 2)
    assert resolve("requirement_coverage", Corpus(ws))["value"] == \
        round(5 / 6, 4)
    empty = resolve("requirement_coverage", Corpus(tmp_path / "none"))
    assert empty["status"] == "absent" and empty["value"] is None


def test_injection_screen_flags_count_flags_and_are_absent_on_empty(tmp_path):
    ws = tmp_path / "ws"
    _run(ws, "pur_a", "run_0001", "live",
         [_screen("pass"), _screen("pass"), _screen("flag")])
    row = resolve("injection_screen_flags", Corpus(ws))
    assert row["value"] == 1.0 and row["n"] == 3
    absent = resolve("injection_screen_flags", Corpus(tmp_path / "none"))
    assert absent["status"] == "absent"


def test_fabrication_count_reads_the_filename_keyed_record(tmp_path):
    ws = tmp_path / "ws"
    _run(ws, "pur_a", "run_0001", "live", [])
    (ws / "pur_a" / "extraction.json").write_text(json.dumps({
        "two_path": {"buyer.pdf": {"tables_diffed": 2,
                                   "findings": [{"table": 0}, {"table": 1}]},
                     "other.pdf": {"tables_diffed": 1, "findings": []}}}))
    row = resolve("extraction_fabrication_count", Corpus(ws))
    assert row["value"] == 2 and row["n"] == 2
    (ws / "pur_a" / "extraction.json").write_text("{not json")
    assert resolve("extraction_fabrication_count", Corpus(ws))["status"] \
        == "absent"


def test_unsourced_and_bench_absences_carry_their_reasons(tmp_path):
    ws = tmp_path / "ws"
    _run(ws, "pur_a", "run_0001", "live", [])
    corpus = Corpus(ws)
    cycle = resolve("cycle_time_days", corpus)
    assert cycle["status"] == "absent" and "CRM" in cycle["absent_reason"]
    gap = resolve("false_gap_rate", corpus)
    assert "release record" in gap["absent_reason"]
    state = resolve("eval_pass_state", corpus)
    assert "docs/releases" in state["absent_reason"]
    assert "P10" not in state["absent_reason"]
