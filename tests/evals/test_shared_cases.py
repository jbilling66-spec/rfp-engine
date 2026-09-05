"""The shared eval seam (B40/D2): the three harnesses delegate their
duplicated parts to engine/evals/cases.py. The refactor's inertness is
proven by the STANDING drift locks — test_poison.py's committed-baseline
check and test_injection_suite.py's recorded-equality check compare
stored fingerprints against recomputed ones, so a delegate that changed
the computation would fail them. This file pins the seam's own contract.
"""

import json

import pytest

from engine.contracts import ContractError
from engine.evals.cases import (files_fingerprint, load_cases,
                                object_fingerprint, write_report)


def test_load_cases_validates_before_anything_runs(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"case_id": "not_a_case"}]),
                    encoding="utf-8")
    with pytest.raises(ContractError):
        load_cases(path)


def test_object_fingerprint_ignores_key_order_never_content():
    same_one = object_fingerprint({"b": 1, "a": [1, 2]})
    same_two = object_fingerprint({"a": [1, 2], "b": 1})
    moved = object_fingerprint({"a": [2, 1], "b": 1})
    assert same_one == same_two  # key order must never stale a baseline
    assert same_one != moved     # content movement must


def test_files_fingerprint_tracks_bytes_and_order(tmp_path):
    one, two = tmp_path / "one.md", tmp_path / "two.md"
    one.write_text("alpha", encoding="utf-8")
    two.write_text("beta", encoding="utf-8")
    ordered = files_fingerprint(one, two)
    assert ordered != files_fingerprint(two, one)
    two.write_text("beta edited", encoding="utf-8")
    assert ordered != files_fingerprint(one, two)
    # M-19 (P26b-3): the roster is framed, so a boundary shift between
    # two files ("ab"+"c" vs "a"+"bc") is a different digest.
    one.write_text("ab", encoding="utf-8"); two.write_text("c", encoding="utf-8")
    shifted_one, shifted_two = tmp_path / "x.md", tmp_path / "y.md"
    shifted_one.write_text("a", encoding="utf-8")
    shifted_two.write_text("bc", encoding="utf-8")
    assert files_fingerprint(one, two) != files_fingerprint(shifted_one,
                                                            shifted_two)


def test_write_report_shape_is_byte_stable(tmp_path):
    report = {"b": 1, "a": {"recall": 0.5}}
    path = write_report(report, tmp_path / "deep" / "r.json")
    text = path.read_text(encoding="utf-8")
    assert text == json.dumps(report, indent=1, sort_keys=True) + "\n"
    assert json.loads(text) == report
