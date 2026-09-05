"""P28 (P1-4): the identifier taxonomy is the domain's, the structured
classes are found by code before any model is trusted, and the scan sees
the forms a residue takes — acronyms, K/MM/rounded fees, Unicode names,
invisible-character splits. Each mechanism has a test that fails without
it (proven red against the pre-P28 module at the step-1 commit).
"""

import unicodedata

from engine.kb.anonymize import (
    PLACEHOLDER_TYPES,
    STRUCTURED_TYPES,
    apply_placeholders,
    detect_structured,
    merge_identifiers,
    normalize_text,
    scan,
    scan_passed,
)

SAMPLES = {
    "CLIENT": "Foxglove Robotics",
    "FEE": "$1,240,000",
    "REFERENCE_NAME": "Jordan Mercer",
    "ORGANIZATION": "Halvorsen Data Systems",
    "CONTACT": "r.calloway@amberview.example",
    "URL": "portal.foxglove.example",
    "ADDRESS": "4120 Harrowgate Blvd, Suite 300",
    "TAX_ID": "47-1234567",
    "REFERENCE_NUMBER": "PO #48812-A",
}

STRUCTURED_PROSE = (
    "Reach r.calloway@amberview.example or (555) 214-8890; the portal is "
    "https://portal.foxglove.example/login and the public site "
    "foxglove-robotics.com; offices at 4120 Harrowgate Blvd, Suite 300; "
    "EIN 47-1234567; the sponsor's SSN 123-45-6789 appeared on one form; "
    "PO #48812-A, Contract No. C-2024-0117, RFP 2025-014, Invoice INV-20431."
)

# Accounting/consulting vocabulary that must NEVER read as an identifier —
# a false positive trains reviewers to ignore the finding (v1).
GUARD_PROSE = (
    "3,800 employees; go-live 2026-07-31; 0.35 rate; reconciled $1,975,000 "
    "to the penny. SOC 2 Type II, ISO 27001, Form 990, GASB 87, ASC 842, "
    "FY2025, a 10-K filing, Section 4.2, HL7 v2, Q3 2025, version 3.1.5, "
    "e.g. the 2024 bid, Contract Management, 24-7 support, 12 Step Program."
)


def test_every_taxonomy_class_substitutes_to_its_typed_placeholder():
    assert set(SAMPLES) == set(PLACEHOLDER_TYPES) - {"REDACTED"}
    for itype, value in SAMPLES.items():
        out = apply_placeholders(f"see {value} here", {value: itype})
        assert out == f"see {PLACEHOLDER_TYPES[itype]} here", (itype, out)


def test_structured_detection_names_every_class_and_only_identifiers():
    found = detect_structured(STRUCTURED_PROSE)
    assert set(found.values()) == set(STRUCTURED_TYPES)
    assert found["r.calloway@amberview.example"] == "CONTACT"
    assert found["(555) 214-8890"] == "CONTACT"
    assert found["https://portal.foxglove.example/login"] == "URL"
    assert found["foxglove-robotics.com"] == "URL"
    assert found["4120 Harrowgate Blvd, Suite 300"] == "ADDRESS"
    assert found["47-1234567"] == "TAX_ID"
    assert found["123-45-6789"] == "TAX_ID"
    for number in ("PO #48812-A", "Contract No. C-2024-0117", "RFP 2025-014",
                   "Invoice INV-20431"):
        assert found[number] == "REFERENCE_NUMBER"


def test_structured_detection_ignores_the_accounting_vocabulary():
    assert detect_structured(GUARD_PROSE) == {}
    assert scan({"card:body": GUARD_PROSE}, []) == []


def test_structured_identifiers_are_substituted_not_merely_blocked():
    """Refusal is not delivery: a firm document that mentions a reference's
    email or the client's PO number comes out anonymized, typed."""
    identifiers = merge_identifiers(detect_structured(STRUCTURED_PROSE),
                                    {"Foxglove Robotics": "CLIENT"})
    out = apply_placeholders(STRUCTURED_PROSE, identifiers)
    for token in ("[CONTACT]", "[URL]", "[ADDRESS]", "[TAX_ID]",
                  "[REFERENCE_NUMBER]"):
        assert token in out, token
    assert scan_passed(scan({"card:body": out}, identifiers)), (
        scan({"card:body": out}, identifiers))


def test_scan_names_each_structured_class_unconditionally():
    findings = scan({"card:body": STRUCTURED_PROSE}, [])
    labels = {f.identifier for f in findings}
    assert labels == {"<contact_info>", "<url>", "<address>", "<tax_id>",
                      "<reference_number>"}
    assert all(f.location == "card:body" for f in findings)


def test_merge_precedence_known_over_typed_over_redacted():
    merged = merge_identifiers(
        {"a@b.example": "CONTACT"},
        {"Foxglove Robotics": "REDACTED", "Halvorsen Data Systems": "REDACTED"},
        {"Halvorsen Data Systems": "ORGANIZATION"},
        {"Foxglove Robotics": "CLIENT", " ": "CLIENT"},
    )
    assert merged == {"a@b.example": "CONTACT",
                      "Foxglove Robotics": "CLIENT",
                      "Halvorsen Data Systems": "ORGANIZATION"}
    # a typed entry is never downgraded by a later fallback
    assert merge_identifiers({"X Corp": "ORGANIZATION"},
                             {"X Corp": "REDACTED"}) == {"X Corp": "ORGANIZATION"}


def test_normalization_defeats_invisible_splits_and_decomposed_unicode():
    decomposed = unicodedata.normalize("NFD", "Renée Okonkwo")
    assert decomposed != "Renée Okonkwo"
    split = "Fox\u00adglove Rob\u200botics"  # soft hyphen, zero-width space
    text = f"{split} and {decomposed} met on site."
    out = apply_placeholders(text, {"Foxglove Robotics": "CLIENT",
                                    "Renée Okonkwo": "REFERENCE_NAME"})
    assert out == "[CLIENT] and [REFERENCE_NAME] met on site."
    assert normalize_text(split) == "Foxglove Robotics"
    # and the scan sees through the same tricks
    findings = scan({"b": text}, ["Foxglove Robotics", "Renée Okonkwo"])
    assert {f.identifier for f in findings} == {"Foxglove Robotics",
                                                "Renée Okonkwo"}


def test_unicode_distinctive_tokens_trip_the_scan():
    findings = scan({"b": "Renée signed off on Friday."}, ["Renée Okonkwo"])
    assert findings and findings[0].matched == "Renée"
    # generic organization words never flag on their own (P28's additions)
    clean = scan({"b": "Their data systems and consulting associates."},
                 ["Halvorsen Data Systems", "Brightwater Consulting Associates"])
    assert clean == []
    assert scan({"b": "Halvorsen handled the cutover."},
                ["Halvorsen Data Systems"])


def test_acronym_variants_trip_the_scan():
    for form in ("CVMC", "C.V.M.C."):
        findings = scan({"b": f"the {form} steering group"},
                        ["Cascade Valley Medical Center"])
        assert findings and findings[0].matched == form, form
    # two-letter initials are not generated (collision cost), lowercase
    # letters are not an acronym, and an embedded run does not match
    assert scan({"b": "FR and cvmc and ACVMCX"},
                ["Foxglove Robotics", "Cascade Valley Medical Center"]) == []


def test_fee_forms_trip_the_scan():
    for restated in ("about $1.24MM", "roughly $1.2M", "$1,240K in fees",
                     "1.24 million dollars", "USD 1,240,000 total",
                     "1,240,000.00 invoiced", "1240K"):
        findings = scan({"b": restated}, ["$1,240,000"])
        assert findings, restated
    assert scan({"b": "about $980K"}, ["$980,000"])
    # the rounding does not fire on an unrelated small figure
    assert scan({"b": "a $12 fee and 1.2 percent"}, ["$1,240,000"]) == []
