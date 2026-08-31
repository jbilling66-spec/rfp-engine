"""The four content acceptance clauses (ROADMAP P7) + disposition
consumption, over the full chain (runs 0001-0005).

Non-vacuity discipline: every mirror/thread/containment assertion is
preceded by a hand-transcribed golden asserted PRESENT in the input
artifact (restating the fixture, never deriving from the code under
test), and every positive flag/canonical assertion has its planted
negative.
"""

import pytest

from engine.drafting.verify import PROPOSED_FLAG, normalize_ws
from engine.kb import KBStore
from tests.drafting.fixtures.drafts import (
    ANSWERED_TEXT,
    CANON_ID,
    CANONICAL_BODY,
    answer_by_ref,
    make_drafter_script,
    read_draft,
    run_drafting_package,
    section_by_id,
)

DELIVERY = "1-delivery-approach"
SPECIAL = "2-special-requirements"

# Hand-transcribed from tests/intake/fixtures/packages.py (the pdf
# package's scripted analyst) — restated, not derived.
PDF_TERMS = ["integrated ERP platform", "human capital management"]


def _texts(section: dict) -> str:
    return " ".join(
        [a.get("prose", "") for a in section.get("answers", [])]
        + [section.get("prose", "")]
    )


@pytest.fixture(scope="module")
def gapcase(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-gapcase")
    script = make_drafter_script()
    pursuit, report = run_drafting_package(tmp, package_id="gapcase",
                                           script=script)
    return tmp, pursuit, report, script


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("draft-pdf")
    script = make_drafter_script()
    pursuit, report = run_drafting_package(tmp, package_id="pdf",
                                           script=script)
    return tmp, pursuit, report, script


# --- acceptance: drafts mirror twin-buyer terminology -------------------

def test_drafts_mirror_buyer_terminology(pdf):
    _, pursuit, report, _ = pdf
    brief = pursuit.read_artifact("brief.frozen.json")
    # Non-vacuity: the planted terminology is really in the frozen brief.
    assert brief["buyer"]["terminology"] == PDF_TERMS
    envelope = read_draft(pursuit)
    drafted = [s for s in envelope["sections"] if s["status"] == "drafted"]
    assert drafted, report
    for section in drafted:
        text = _texts(section)
        for term in PDF_TERMS:
            assert term in text, (section["section_id"], term)


# --- acceptance: + thread themes ----------------------------------------

@pytest.mark.parametrize("chain", ["gapcase", "pdf"])
def test_drafts_thread_approved_themes(chain, request):
    _, pursuit, _, _ = request.getfixturevalue(chain)
    approved = pursuit.read_artifact(
        "brief.frozen.json")["win_themes"]["approved"]
    # Non-vacuity: exactly the two judge-kept themes survived Gate 1
    # (KEEP_INDEXES golden, restating the strategy fixture).
    assert len(approved) == 2
    assert all(theme.startswith("Win theme") for theme in approved)
    envelope = read_draft(pursuit)
    drafted = [s for s in envelope["sections"] if s["status"] == "drafted"]
    assert drafted
    for section in drafted:
        for theme in approved:  # the exact approved strings, threaded
            assert theme in _texts(section), (section["section_id"], theme)


# --- acceptance: canonical block near-verbatim, card cited --------------

def test_canonical_block_reproduced_near_verbatim(gapcase):
    tmp, pursuit, _, _ = gapcase
    # Non-vacuity: the planted card is canonical in the store AND the
    # plan's own selection picked it (the RAG ban stayed intact).
    front, body = KBStore(tmp / "kb").read_card(CANON_ID)
    assert front["canonical_block"] is True
    assert body == CANONICAL_BODY
    frozen = pursuit.read_artifact("plan.frozen.json")
    delivery_plan = next(s for s in frozen["sections"]
                         if s["section_id"] == DELIVERY)
    assert CANON_ID in {h["kb_id"] for h in delivery_plan["kb_hits"]}

    delivery = section_by_id(read_draft(pursuit), DELIVERY)
    assert delivery["status"] == "drafted"
    # Independent containment re-check — not verify.py's verdict.
    assert normalize_ws(CANONICAL_BODY) in normalize_ws(_texts(delivery))
    assert {"kb_id": CANON_ID, "verified": True} in delivery["canonical"]
    assert CANON_ID in delivery["cards_cited"]


def test_altered_canonical_recorded_and_still_cited(tmp_path):
    pursuit, _ = run_drafting_package(
        tmp_path, script=make_drafter_script(plant_alter_canonical=True))
    delivery = section_by_id(read_draft(pursuit), DELIVERY)
    assert {"kb_id": CANON_ID, "verified": False} in delivery["canonical"]
    assert CANON_ID in delivery["cards_cited"]  # opened and demanded
    assert any("not reproduced near-verbatim" in w
               for w in delivery["warnings"])


# --- acceptance: [proposed approach] flags present ----------------------

def test_proposed_approach_flags_present(gapcase):
    _, pursuit, _, _ = gapcase
    special = section_by_id(read_draft(pursuit), SPECIAL)
    flagged = answer_by_ref(special, "2.0.2")  # draft_flagged at Gate 2
    assert PROPOSED_FLAG in flagged["prose"]
    assert flagged["proposed_approach"] is True
    assert special["proposed_approach"] is True


def test_missing_flag_recorded_as_finding(tmp_path):
    pursuit, _ = run_drafting_package(
        tmp_path, script=make_drafter_script(plant_omit_flag=True))
    special = section_by_id(read_draft(pursuit), SPECIAL)
    flagged = answer_by_ref(special, "2.0.2")
    assert PROPOSED_FLAG not in flagged["prose"]
    assert flagged["proposed_approach"] is False
    assert any("draft_flagged but no" in w for w in special["warnings"])


# --- disposition consumption (B24 -> B31(7)) ----------------------------

def test_answered_disposition_threads_the_answer(gapcase):
    _, pursuit, _, _ = gapcase
    special = section_by_id(read_draft(pursuit), SPECIAL)
    answered = answer_by_ref(special, "2.0.1")
    assert answered["status"] == "drafted"
    assert ANSWERED_TEXT in answered["prose"]


def test_reframed_direction_threads_without_auto_flag(tmp_path):
    note = "Lead with the adjacent managed-service strengths instead."
    pursuit, _ = run_drafting_package(tmp_path, dispose=[
        {"section_id": SPECIAL, "gap_id": "gap_pur_gapcase_plan_01",
         "action": "answered", "answer": ANSWERED_TEXT},
        {"section_id": SPECIAL, "gap_id": "gap_pur_gapcase_plan_02",
         "action": "reframed", "note": note},
    ])
    special = section_by_id(read_draft(pursuit), SPECIAL)
    assert note in _texts(special)  # the direction reached the drafter
    # A reframe is human-directed — no automatic flag (mandatory_review
    # is already code-forced on the plan). Non-vacuous: the flag DOES
    # appear when demanded (test_proposed_approach_flags_present).
    assert PROPOSED_FLAG not in _texts(special)
    assert special.get("proposed_approach") is False


def test_omit_approved_slot_never_reaches_the_model(tmp_path):
    script = make_drafter_script()
    pursuit, _ = run_drafting_package(tmp_path, script=script, dispose=[
        {"section_id": SPECIAL, "gap_id": "gap_pur_gapcase_plan_01",
         "action": "omit_approved", "note": "buyer strikes this section"},
        {"section_id": SPECIAL, "gap_id": "gap_pur_gapcase_plan_02",
         "action": "answered", "answer": ANSWERED_TEXT},
    ])
    special = section_by_id(read_draft(pursuit), SPECIAL)
    omitted = answer_by_ref(special, "2.0.1")
    assert omitted["status"] == "omitted"
    assert omitted["reason"] == "buyer strikes this section"
    # No state_if_not_offered instruction on the committed twin — the
    # cell stays honestly empty (the constraints suite proves the
    # instructed pair on a workbook variant).
    assert omitted["omission_stated"] is False
    assert "prose" not in omitted
    # The model was never asked for it: no SLOT line for 2.0.1 in the
    # section's draft prompt.
    special_prompts = [p for p in script["section_drafter"].prompts
                       if p.startswith("Task: draft.")
                       and "SECTION: 2. Special Requirements" in p]
    assert len(special_prompts) == 1
    assert "| ref 2.0.1" not in special_prompts[0]
    assert "| ref 2.0.2" in special_prompts[0]


def test_undisposed_open_gap_slot_awaits_without_spend(tmp_path):
    script = make_drafter_script()
    pursuit, _ = run_drafting_package(tmp_path, script=script, dispose=[
        {"section_id": SPECIAL, "gap_id": "gap_pur_gapcase_plan_02",
         "action": "answered", "answer": ANSWERED_TEXT},
    ])  # gap_01 rides to drafting still open
    special = section_by_id(read_draft(pursuit), SPECIAL)
    waiting = answer_by_ref(special, "2.0.1")
    assert waiting["status"] == "awaiting_disposition"
    assert "invention" in waiting["reason"]
    special_prompts = [p for p in script["section_drafter"].prompts
                       if p.startswith("Task: draft.")
                       and "SECTION: 2. Special Requirements" in p]
    assert "| ref 2.0.1" not in special_prompts[0]
