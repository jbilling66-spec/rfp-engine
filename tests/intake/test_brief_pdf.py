"""Acceptance: the synthetic PDF produces a complete brief; weights match
the hand-extraction golden; the AI clause surfaces; OCI is routed, never
adjudicated."""

from tests.intake.fixtures.packages import HAND_WEIGHTS, run_package

# every key B17 allows on a red flag — an adjudication field would be a
# schema change, and this set is asserted to prove none exists
_B17_FLAG_KEYS = {"kind", "detail", "excerpt", "source_location", "detected_by", "routed_to"}


def test_pdf_produces_complete_brief(tmp_path):
    pursuit, report = run_package(tmp_path, "pdf")
    assert report.status == "complete"
    assert report.misses == []
    brief = pursuit.read_artifact("brief.json")
    assert brief["buyer"]["name"] == "Northwind Regional Health"
    assert brief["procurement"]["response_structure"] == "free_flow"
    assert brief["procurement"]["submission_method"] == "Northwind procurement portal"
    assert brief["procurement"]["required_forms"] == [
        "Form A (Vendor Certification)", "Form B (Pricing Workbook)",
    ]


def test_pdf_weights_match_hand_extraction_exactly(tmp_path):
    pursuit, report = run_package(tmp_path, "pdf")
    matrix = pursuit.read_artifact("brief.json")["requirements_matrix"]
    weighted = [(row["requirement"], row["weight"], row["weight_basis"])
                for row in matrix if "weight" in row]
    assert weighted == HAND_WEIGHTS["pdf"]  # golden 2: exact match
    assert not any("not 100" in w for w in report.warnings)  # 40+25+20+15 == 100
    mandatory = [row["ref"] for row in matrix if row.get("mandatory")]
    assert mandatory == ["3.1", "3.2", "3.3", "3.4"]


def test_pdf_deadlines_verbatim_plus_parsed_iso(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf")
    deadlines = pursuit.read_artifact("brief.json")["procurement"]["deadlines"]
    by_label = {d["label"]: d for d in deadlines}
    questions = by_label["Written questions due"]
    assert questions["date_text"] == "August 8, 2026"  # buyer's words, verbatim
    assert questions["date"] == "2026-08-08"
    proposal = by_label["Proposal due"]
    assert proposal["date_text"] == "August 29, 2026 at 3:00 PM Central Time"
    assert proposal["date"] == "2026-08-29"
    assert proposal["source_location"] == "pdf-twin.pdf p1"


def test_ai_clause_surfaces_as_first_class_flag(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf")
    flags = pursuit.read_artifact("brief.json")["procurement"]["red_flags"]
    ai = [f for f in flags if f["kind"] == "ai_use"]
    assert len(ai) == 1
    assert "generative AI" in ai[0]["excerpt"]
    assert ai[0]["source_location"].endswith("p2")


def test_oci_flag_is_routed_never_adjudicated(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf")
    flags = pursuit.read_artifact("brief.json")["procurement"]["red_flags"]
    oci = [f for f in flags if f["kind"] == "independence_oci"]
    assert len(oci) == 1
    assert oci[0]["routed_to"] == "conflicts_process"
    assert "conflict of interest" in oci[0]["excerpt"]
    # structurally no verdict: the flag carries only B17's keys, none of
    # which can express an assessment
    assert set(oci[0]) <= _B17_FLAG_KEYS


def test_clean_pdf_has_no_injection_or_hidden_flags(tmp_path):
    pursuit, _ = run_package(tmp_path, "pdf")
    kinds = {f["kind"] for f in
             pursuit.read_artifact("brief.json")["procurement"]["red_flags"]}
    assert "injection" not in kinds
    assert "hidden_content" not in kinds
