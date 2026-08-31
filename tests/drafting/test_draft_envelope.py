"""The draft artifact of record: schema-valid, complete before the
first model call (v1 prepass lesson), bound to the frozen plan, and the
live plan.json touched in exactly one field (B31(6)).
"""

import copy
import hashlib

import pytest

from engine.contracts import validate
from engine.workspace import PursuitDir
from tests.drafting.fixtures.drafts import (
    make_drafter_script,
    read_draft,
    run_drafting_package,
    section_by_id,
)

DELIVERY = "1-delivery-approach"
SPECIAL = "2-special-requirements"


@pytest.fixture(scope="module")
def gapcase(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-envelope")
    pursuit, report = run_drafting_package(tmp, script=make_drafter_script())
    assert report.status == "complete"
    return pursuit


def test_envelope_validates_and_names_every_section(gapcase):
    envelope = read_draft(gapcase)
    validate("draft", envelope)
    assert envelope["status"] == "complete"
    assert envelope["revision_n"] == 0
    plan_sections = [s["section_id"] for s in
                     gapcase.read_artifact("plan.frozen.json")["sections"]]
    assert [s["section_id"] for s in envelope["sections"]] == plan_sections


def test_envelope_binds_to_the_frozen_plan(gapcase):
    envelope = read_draft(gapcase)
    frozen_bytes = (gapcase.root / "plan.frozen.json").read_bytes()
    assert envelope["plan_sha256"] == hashlib.sha256(frozen_bytes).hexdigest()


def test_prepass_names_every_slot_owed_before_any_call(tmp_path):
    # v1 lesson: a run killed before its first model call still names
    # every slot owed, durably, in the artifact of record.
    with pytest.raises(RuntimeError, match="killed mid-run"):
        run_drafting_package(tmp_path, script=make_drafter_script(
            fail_on_section="1. Delivery Approach"))
    pursuit = PursuitDir(tmp_path, "pur_gapcase")
    envelope = read_draft(pursuit)
    validate("draft", envelope)
    assert envelope["status"] == "in_progress"
    for section_id in (DELIVERY, SPECIAL):
        section = section_by_id(envelope, section_id)
        assert section["status"] == "pending"
        assert section["reason"] == "not reached — resume completes it"
        answers = {a["ref_id"]: a["status"] for a in section["answers"]}
        assert set(answers.values()) == {"pending"}
        assert len(answers) == 2  # both prose slots named
    plan = pursuit.read_artifact("plan.json")
    assert {s.get("draft_status") for s in plan["sections"]} == {"planned"}
    frozen = pursuit.read_artifact("plan.frozen.json")
    assert all("draft_status" not in s for s in frozen["sections"])


def test_plan_touched_only_in_draft_status(gapcase):
    # v1's "drafting never touches the plan" — deliberately inverted for
    # exactly one field (live-copy-vs-record, B22(9)).
    live = gapcase.read_artifact("plan.json")
    frozen = gapcase.read_artifact("plan.frozen.json")
    stripped = copy.deepcopy(live)
    statuses = []
    for section in stripped["sections"]:
        statuses.append(section.pop("draft_status", None))
    assert stripped == frozen
    assert set(statuses) == {"drafted"}  # both gapcase sections drafted


def test_non_draftable_sections_carry_no_draft_status(tmp_path):
    # The structured twin's pricing sheet shape-skips (B28(4)): absence
    # of draft_status is the honest state — no lane owns it at P7.
    pursuit, report = run_drafting_package(tmp_path, package_id="xlsx",
                                           script=make_drafter_script())
    assert report.status == "complete"
    envelope = read_draft(pursuit)
    skipped = [s["section_id"] for s in envelope["sections"]
               if s["status"] == "skipped_non_prose"]
    assert skipped  # the twin really carries a non-prose section
    live = {s["section_id"]: s
            for s in pursuit.read_artifact("plan.json")["sections"]}
    for section_id in skipped:
        assert "draft_status" not in live[section_id]
    drafted = [s["section_id"] for s in envelope["sections"]
               if s["status"] == "drafted"]
    assert drafted
    for section_id in drafted:
        assert live[section_id]["draft_status"] == "drafted"
