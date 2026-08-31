"""Acceptance: a planted injection string flags — and changes NOTHING else.

The injected package uses the injected PDF bytes under the clean twin's
FILENAME and pursuit_id, so the only input difference is the planted
sentence; the only output difference must be the injection flags.
"""

import copy
import json
import re

from engine.intake.brief import IntakeDoc, IntakePackage
from engine.runlog import read_run
from tests.fixtures.intake_twins import INJECTION_SENTENCE
from tests.intake.fixtures.packages import FIXTURES, _wire_from_prompt, run_package


def _injected_package(tmp_path) -> IntakePackage:
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()
    target = doc_dir / "pdf-twin.pdf"  # clean twin's name, injected bytes
    target.write_bytes((FIXTURES / "pdf-twin-injected.pdf").read_bytes())
    return IntakePackage(pursuit_id="pur_pdf",
                         docs=[IntakeDoc(path=target, kind="rfp_main")])


def test_planted_injection_flags_with_no_behavior_change(tmp_path):
    clean_pursuit, _ = run_package(tmp_path / "clean", "pdf")
    injected_pursuit, report = run_package(
        tmp_path / "inj", "", package=_injected_package(tmp_path)
    )
    clean = clean_pursuit.read_artifact("brief.json")
    injected = injected_pursuit.read_artifact("brief.json")

    flags = [f for f in injected["procurement"]["red_flags"] if f["kind"] == "injection"]
    assert flags, "the planted sentence must flag"
    assert all(f["detected_by"] in ("screen", "both") for f in flags)
    assert any(f["detected_by"] == "both" for f in flags)  # screen and model agreed
    assert any(f["source_location"] == "pdf-twin.pdf p2" for f in flags)
    assert any(INJECTION_SENTENCE[:40] in f["excerpt"] for f in flags)

    # strip the injection flags -> the briefs are EQUAL (no behavior change)
    stripped = copy.deepcopy(injected)
    stripped["procurement"]["red_flags"] = [
        f for f in stripped["procurement"]["red_flags"] if f["kind"] != "injection"
    ]
    assert stripped == clean


def test_prompts_identical_except_unmutated_planted_sentence(tmp_path):
    captured = {}

    def capturing_factory(slot):
        def capture(prompt: str) -> str:
            captured[slot] = prompt
            return _wire_from_prompt(prompt)
        return capture

    run_package(tmp_path / "clean", "pdf",
                script={"intake_analyst": capturing_factory("clean")})
    run_package(tmp_path / "inj", "", package=_injected_package(tmp_path),
                script={"intake_analyst": capturing_factory("injected")})

    extra = set(captured["injected"].splitlines()) - set(captured["clean"].splitlines())
    assert extra == {INJECTION_SENTENCE}  # detection never mutates the text

    # and the sentence sits INSIDE an S1 frame, not loose in the prompt
    blocks = re.findall(r"<buyer_document.*?</buyer_document>",
                        captured["injected"], re.S)
    assert any(INJECTION_SENTENCE in b for b in blocks)


def test_validation_records_flag_and_pass(tmp_path):
    clean_pursuit, _ = run_package(tmp_path / "clean", "pdf")
    injected_pursuit, _ = run_package(
        tmp_path / "inj", "", package=_injected_package(tmp_path)
    )

    def screen_results(pursuit):
        records = read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")
        return [r["validation"]["result"] for r in records
                if r["record_type"] == "validation"
                and r["validation"]["check"] == "injection_screen"]

    assert screen_results(clean_pursuit) == ["pass"]
    assert "flag" in screen_results(injected_pursuit)  # the B18 metric can count it


def test_model_only_injection_flag_still_lands(tmp_path):
    def model_only(prompt: str) -> str:
        wire = json.loads(_wire_from_prompt(prompt))
        wire["red_flags"].append({
            "kind": "injection",
            "detail": "phrasing aimed at an AI assistant",
            "excerpt": "A subtle instruction the screen lexicon does not cover.",
            "source_location": "pdf-twin.pdf p1",
        })
        return json.dumps(wire)

    pursuit, _ = run_package(tmp_path, "pdf", script={"intake_analyst": model_only})
    flags = [f for f in pursuit.read_artifact("brief.json")["procurement"]["red_flags"]
             if f["kind"] == "injection"]
    assert len(flags) == 1
    assert flags[0]["detected_by"] == "model"  # either-alone-fires
    records = read_run(pursuit.root / "runs" / "run_0001" / "run.jsonl")
    model_screens = [r for r in records if r["record_type"] == "validation"
                     and r.get("stage") == "bid_brief"
                     and r["validation"]["check"] == "injection_screen"]
    assert [r["validation"]["result"] for r in model_screens] == ["flag"]
