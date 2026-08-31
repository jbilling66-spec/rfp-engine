"""The synthetic ERP past-response corpus (K2: 10+ seeds, known outcomes).

Twelve firm-authored responses across five invented clients, with planted
synthetic identifiers (client names, fees, reference contacts) whose
ground truth lives in PLANTED. The prose is the single source: WIRE — the
canned ingestion-agent output FakeCaller serves — echoes each document's
sections verbatim (a faithful model that segments but does not
descriptorize; the code post-pass owns anonymization), plus hand-annotated
summaries and facets per section.

Deliberate structure:
- resp_02 §2 and resp_03 §1 are near-duplicates WITHIN a client (both won —
  tie-break falls to kb_id).
- resp_05 §1 and resp_07 §1 are near-duplicates ACROSS clients (lost vs
  won — the won variant survives and the merged card must carry BOTH
  clients, the D1 purge-safety case).
- resp_08 wraps its client name across a line break; possessive forms
  appear in resp_06/resp_07 — the substitution/scan variants earn their keep.

All names are invented (tripwire-safe); style per B6's precedent.
"""

import json
import re
from pathlib import Path

from engine.kb import KBStore
from engine.kb.ingest import IngestReport, SourceDoc, ingest_document
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.runlog import RunLogger
from engine.version import engine_version

FIXTURES = Path(__file__).resolve().parent
RESPONSES = FIXTURES / "responses"

_META = {
    "resp_01": {
        "client": "Meridian Health Partners",
        "pursuit": "pur_meridian_erp_2024", "outcome": "won", "date": "2024-09-12",
        "descriptor": "a seven-hospital regional health system, ~11,000 employees",
        "fee": "$1,975,000", "contacts": ["Dana Whitfield"],
        "sections": [
            {"section_types": ["methodology"], "type_tags": ["methodology"],
             "summary": "Two-wave ERP cutover methodology for a seven-hospital "
                        "regional health system: wave sequencing, payroll parallel "
                        "gates, rollback rehearsal, go/no-go criteria.\n"
                        "Open for the cutover gate structure."},
            {"section_types": ["data_migration"], "type_tags": ["data_migration"],
             "summary": "Data migration factory: seven mock conversions, "
                        "chart-of-accounts crosswalk governance, reconciliation "
                        "packets with hash totals.\n"
                        "Open for the mock-conversion cadence."},
        ],
    },
    "resp_02": {
        "client": "Meridian Health Partners",
        "pursuit": "pur_meridian_intg_2025", "outcome": "won", "date": "2025-03-20",
        "descriptor": "a seven-hospital regional health system, ~11,000 employees",
        "fee": "$2,340,000", "contacts": ["Dana Whitfield"],
        "sections": [
            {"section_types": ["integration_approach"], "type_tags": ["integration"],
             "summary": "Interface inventory and HL7 v2 / FHIR R4 integration "
                        "approach for a hospital ERP: contract sheets, retirement "
                        "of duplicative feeds, payroll-dependency sequencing.\n"
                        "Open for the interface contract-sheet fields."},
            {"section_types": ["testing"], "type_tags": ["integration"],
             "summary": "Three-pass interface testing: synthetic messages, "
                        "thirty-day production replay, double-peak soak test with "
                        "live error-queue procedures.\nOpen for exit criteria."},
        ],
    },
    "resp_03": {
        "client": "Meridian Health Partners",
        "pursuit": "pur_meridian_qa_2025", "outcome": "won", "date": "2025-06-02",
        "descriptor": "a seven-hospital regional health system, ~11,000 employees",
        "fee": "$1,180,000", "contacts": [],
        "sections": [
            {"section_types": ["testing"], "type_tags": ["methodology"],
             "summary": "Three-pass interface testing methodology with production "
                        "replay and soak testing; exit on zero unexplained "
                        "mismatches.\nOpen for the pass structure."},
            {"section_types": ["staffing"], "type_tags": ["resource_role"],
             "summary": "Blended onshore/offshore staffing model with named client "
                        "counterparts and quarterly rotation for knowledge "
                        "continuity.\nOpen for team composition."},
        ],
    },
    "resp_04": {
        "client": "Cascade Valley Medical Center",
        "pursuit": "pur_cascade_erp_2024", "outcome": "won", "date": "2024-11-05",
        "descriptor": "a two-campus community medical center, ~4,200 employees",
        "fee": "$2,870,000", "contacts": ["Priya Raghavan"],
        "sections": [
            {"section_types": ["methodology"], "type_tags": ["methodology", "governance"],
             "summary": "Sprint-cadence project management inside stage gates: "
                        "decision log with auto-escalation, one-page scope-impact "
                        "template.\nOpen for the PMO mechanics."},
            {"section_types": ["governance"], "type_tags": ["governance"],
             "summary": "Three-tier governance: workstream sync, program board, "
                        "executive steering; red-risk escalation rule.\n"
                        "Open for the escalation thresholds."},
        ],
    },
    "resp_05": {
        "client": "Cascade Valley Medical Center",
        "pursuit": "pur_cascade_opt_2025", "outcome": "lost", "date": "2025-04-18",
        "descriptor": "a two-campus community medical center, ~4,200 employees",
        "fee": "$940,000", "contacts": ["Priya Raghavan"],
        "sections": [
            {"section_types": ["training"], "type_tags": ["ocm"],
             "summary": "Role-based training and change management: super-users, "
                        "teach-the-workflow curricula, measured adoption with "
                        "targeted refreshers.\nOpen for the adoption metrics."},
            {"section_types": ["pricing_narrative"], "type_tags": ["commercial_pricing"],
             "summary": "Milestone-based fixed-fee pricing with capped contingency "
                        "pool returned if unused.\nOpen for the payment structure."},
        ],
    },
    "resp_06": {
        "client": "Harborlight Insurance Group",
        "pursuit": "pur_harborlight_sec_2024", "outcome": "shortlisted",
        "date": "2024-08-22",
        "descriptor": "a regional property-and-casualty insurer, ~2,600 employees",
        "fee": "$1,650,000", "contacts": ["Marcus Ellison"],
        "sections": [
            {"section_types": ["security_compliance"], "type_tags": ["security_compliance"],
             "summary": "Security and compliance for a regulated insurer: "
                        "segregation of duties in workflow, automated access "
                        "recertification, SIEM audit logging.\nOpen for the SoD rules."},
            {"section_types": ["reporting"], "type_tags": ["product_expertise"],
             "summary": "Embedded analytics replacing a legacy warehouse: governed "
                        "semantic layer, close-cycle reporting cut from nine days "
                        "to four.\nOpen for the semantic-layer design."},
        ],
    },
    "resp_07": {
        "client": "Harborlight Insurance Group",
        "pursuit": "pur_harborlight_erp_2025", "outcome": "won", "date": "2025-05-30",
        "descriptor": "a regional property-and-casualty insurer, ~2,600 employees",
        "fee": "$2,215,000", "contacts": ["Marcus Ellison"],
        "sections": [
            {"section_types": ["training"], "type_tags": ["ocm"],
             "summary": "Role-based training and change management: super-users, "
                        "teach-the-workflow curricula, measured adoption with "
                        "targeted refreshers.\nOpen for the adoption metrics."},
            {"section_types": ["support_model"], "type_tags": ["support_hypercare"],
             "summary": "Four-week hypercare command center: floor-walkers, triage "
                        "SLAs, criteria-based exit to steady-state support.\n"
                        "Open for the exit thresholds."},
        ],
    },
    "resp_08": {
        "client": "Bluegrass Municipal Utilities",
        "pursuit": "pur_bluegrass_pay_2024", "outcome": "won", "date": "2024-10-14",
        "descriptor": "a municipal utility, ~1,840 employees, unionized workforce",
        "fee": "$760,000", "contacts": ["Sofia Camacho"],
        "sections": [
            {"section_types": ["testing"], "type_tags": ["methodology"],
             "summary": "Payroll parallel testing for a utility: four full cycles, "
                        "employee-level register comparison, 100% net-pay match "
                        "exit, union pay-rule scenarios.\n"
                        "Open for variance classification."},
            {"section_types": ["integration_approach"], "type_tags": ["integration"],
             "summary": "Utility interface inventory: retire/replace/carry-forward "
                        "classification, payroll-dependency build sequencing, "
                        "rehearsed cutover.\nOpen for the sequencing logic."},
        ],
    },
    "resp_09": {
        "client": "Bluegrass Municipal Utilities",
        "pursuit": "pur_bluegrass_erp_2025", "outcome": "lost", "date": "2025-02-11",
        "descriptor": "a municipal utility, ~1,840 employees, unionized workforce",
        "fee": "$1,430,000", "contacts": ["Sofia Camacho"],
        "sections": [
            {"section_types": ["timeline"], "type_tags": ["methodology"],
             "summary": "Sixteen-month milestone timeline anchored to the fiscal "
                        "year; written entry/exit criteria per milestone; fee "
                        "mapped to acceptance.\nOpen for the stage plan."},
            {"section_types": ["governance"], "type_tags": ["governance"],
             "summary": "Utility ERP risk management: named-owner mitigations "
                        "proven by tests, standing board review.\n"
                        "Open for the top risk patterns."},
        ],
    },
    "resp_10": {
        "client": "Tallgrass County Schools",
        "pursuit": "pur_tallgrass_erp_2024", "outcome": "won", "date": "2024-07-19",
        "descriptor": "a K-12 public school district, ~3,100 employees",
        "fee": "$520,000", "contacts": ["Aaron Tuck"],
        "sections": [
            {"section_types": ["exec_summary"], "type_tags": ["differentiator"],
             "summary": "Executive summary exemplar for a K-12 district: payroll "
                        "continuity commitment, state reporting compliance, "
                        "usability framing.\nOpen for the structure."},
            {"section_types": ["staffing"], "type_tags": ["resource_role"],
             "summary": "Small named-team staffing for a district implementation, "
                        "supplemented by district business office staff.\n"
                        "Open for role composition."},
        ],
    },
    "resp_11": {
        "client": "Tallgrass County Schools",
        "pursuit": "pur_tallgrass_data_2025", "outcome": "shortlisted",
        "date": "2025-01-28",
        "descriptor": "a K-12 public school district, ~3,100 employees",
        "fee": "$685,000", "contacts": [],
        "sections": [
            {"section_types": ["data_migration"], "type_tags": ["data_migration"],
             "summary": "District data migration: state-mandated account codes "
                        "preserved, position-control history converted in full, "
                        "penny-level reconciliation.\nOpen for the mock-conversion "
                        "plan."},
            {"section_types": ["testing"], "type_tags": ["industry_experience"],
             "summary": "State-reporting test harness generating mandated exports "
                        "compared field-by-field to legacy submissions.\n"
                        "Open for the harness design."},
        ],
    },
    "resp_12": {
        "client": "Tallgrass County Schools",
        "pursuit": "pur_tallgrass_ocm_2025", "outcome": "won", "date": "2025-06-25",
        "descriptor": "a K-12 public school district, ~3,100 employees",
        "fee": "$1,050,000", "contacts": ["Aaron Tuck"],
        "sections": [
            {"section_types": ["training"], "type_tags": ["ocm"],
             "summary": "School-year-aware change communications: per-audience "
                        "message tracks, quick-reference cards for secretaries.\n"
                        "Open for the calendar rules."},
            # P13/C8: the Q&A section is a chunk like any other now (code
            # segments) — its annotation is the catalog surface for the
            # distilled qa_pairs the dedup folds into it.
            {"section_types": ["support_model"],
             "type_tags": ["support_hypercare"],
             "summary": "Q&A exemplars: how long hypercare runs after "
                        "go-live (criteria-based exit, not calendar) and "
                        "whether district staff need backfill during the "
                        "project.\nOpen for the answer wording."},
        ],
        "qa_pairs": [
            {"question": "How long does hypercare run after go-live?",
             "answer": "Four weeks per wave as the baseline, extended one week at "
                       "a time if ticket volumes stay above the agreed threshold "
                       "— exit is criteria-based, not calendar-based."},
            {"question": "Will district staff need to be backfilled during the "
                         "project?",
             "answer": "Plan for a 0.5 FTE backfill for the payroll lead and "
                       "business manager during parallel-testing months; other "
                       "roles absorb the work within normal duties."},
        ],
    },
}


def _doc_text(doc_id: str) -> str:
    return (RESPONSES / f"{doc_id}.md").read_text(encoding="utf-8")


def _parsed_sections(doc_id: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## ", _doc_text(doc_id), flags=re.MULTILINE)[1:]
    return [
        (part.splitlines()[0].strip(), "\n".join(part.splitlines()[1:]).strip())
        for part in parts
    ]


def _wire(doc_id: str) -> str:
    """v2 wire (P13/C8): the engine segments — each '## ' section is one
    chunk (no fixture doc carries sub-headings or tables, checked at C8)
    — and the scripted model annotates by chunk index. A qa_sections
    entry keeps its chunk unannotated (defaults apply) while its
    distilled qa_pairs ride alongside, mirroring a model that spent its
    annotation on the Q&A."""
    meta = _META[doc_id]
    skip = set(meta.get("qa_sections", []))
    n_sections = len(_parsed_sections(doc_id))
    kept = [i for i in range(n_sections) if i not in skip]
    annotations = [
        {"chunk": index, "summary": annot["summary"],
         "section_types": annot["section_types"],
         "type_tags": annot["type_tags"]}
        for index, annot in zip(kept, meta["sections"], strict=True)
    ]
    identifiers = (
        [{"value": meta["client"], "type": "CLIENT"},
         {"value": meta["fee"], "type": "FEE"}]
        + [{"value": c, "type": "REFERENCE_NAME"} for c in meta["contacts"]]
    )
    return json.dumps({
        "chunk_annotations": annotations,
        "qa_pairs": meta.get("qa_pairs", []),
        "identifiers": identifiers,
        "client_descriptor": meta["descriptor"],
    })


WIRE = {doc_id: _wire(doc_id) for doc_id in _META}

SCRIPT = {
    "ingestion_agent":
        lambda prompt: WIRE[re.search(r"# DOC:(\w+)", prompt).group(1)]
}

SOURCE_DOCS = [
    SourceDoc(
        doc_id=doc_id,
        text=_doc_text(doc_id),
        source_client=meta["client"],
        source_pursuit=meta["pursuit"],
        outcome=meta["outcome"],
        date=meta["date"],
        authored_by="firm",
        known_identifiers={meta["client"]: "CLIENT"},
    )
    for doc_id, meta in _META.items()
]

PLANTED = {
    doc_id: [meta["client"], meta["fee"], *meta["contacts"]]
    for doc_id, meta in _META.items()
}


# --------------------------------------------------------- curated layer (P8)
# The committed store's governed additions (B34(26)), seeded through this
# one source so the seed-store golden stays the single truth. Fact-sheet
# cards are the Claim Auditor's verification base and are SEARCH-INVISIBLE
# (card_search skips the layer — the drafter must never condition on the
# auditor's answer key). Reference facts are descriptor-form in public
# text; the client names live only in the restricted identifier maps (the
# P2 discipline — the planted-identifier sweep stays clean). Content:
# docs/redline-batch.md §E, approved as-is (B34-addendum), provisional
# until the J3.5 pre-milestone cleanup.

_MERIDIAN = "Meridian Health Partners"
_CASCADE = "Cascade Valley Medical Center"
_HARBORLIGHT = "Harborlight Insurance Group"
_BLUEGRASS = "Bluegrass Municipal Utilities"
_TALLGRASS = "Tallgrass County Schools"

_V, _R = "2026-06-15", "2027-06-15"  # default verified / review_due

# (title, fact text, owner, verified_date, review_due, source_client|None)
FACT_SHEET: list[tuple[str, str, str, str, str, str | None]] = [
    ("SOC 2 Type II attestation",
     "SOC 2 Type II attestation for hosted operations, current period ending 2026-11-30.",
     "Compliance Lead", _V, "2026-11-30", None),
    ("ISO 27001 certificate",
     "ISO 27001 certificate covering all delivery centers, recertified 2026-03.",
     "Compliance Lead", _V, "2027-03-01", None),
    ("HIPAA compliance program",
     "HIPAA compliance program, independently audited annually; last audit completed 2026-05.",
     "Compliance Lead", _V, _R, None),
    ("Platform partnership level",
     "Platform partnership level: certified implementation partner, mid-market tier, renewed 2026-01.",
     "Alliances Lead", _V, "2027-01-31", None),
    ("Independent penetration test",
     "Independent penetration test completed 2026-04.",
     "Compliance Lead", _V, "2027-04-30", None),
    ("Professional liability coverage",
     "Professional liability coverage: $10M per occurrence.",
     "Operations Lead", _V, _R, None),
    ("Certified ERP consultants",
     "14 certified ERP consultants on staff.",
     "Practice Lead", _V, _R, None),
    ("Certified data-migration specialists",
     "6 certified data-migration specialists on staff.",
     "Practice Lead", _V, _R, None),
    ("Consulting headcount",
     "Firm consulting headcount: 220 across three regional offices.",
     "Practice Lead", _V, _R, None),
    ("Average consultant tenure",
     "Average consultant tenure: 6.2 years.",
     "Practice Lead", _V, _R, None),
    ("Onshore-only healthcare delivery",
     "Onshore-only delivery for regulated healthcare clients.",
     "Practice Lead", _V, _R, None),
    ("Engagement partner A. Winslow",
     "Engagement partner A. Winslow — 15 years of ERP advisory experience.",
     "Practice Lead", _V, _R, None),
    ("Delivery lead J. Marsh",
     "Delivery lead J. Marsh — 11 ERP implementations across healthcare and public sector.",
     "Practice Lead", _V, _R, None),
    ("Migration architect R. Okafor",
     "Migration architect R. Okafor — led 7 patient and financial record migrations.",
     "Practice Lead", _V, _R, None),
    ("Training practice lead T. Vasquez",
     "Training practice lead T. Vasquez — designed role-based curricula for 9 go-lives.",
     "Practice Lead", _V, _R, None),
    ("PMO methodology Pathway v4",
     "PMO methodology \"Pathway\" v4, released 2025-09, gate-review based.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Payroll parallel-run standard",
     "Payroll parallel-run standard: four full parallel cycles before cutover.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Cutover rehearsal standard",
     "Cutover rehearsal standard: two complete rehearsal cycles with documented rollback criteria.",
     "Delivery Excellence Lead", _V, _R, None),
    ("OCM toolkit Adopt",
     "OCM toolkit \"Adopt\": readiness surveys and champion program templates.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Training delivery model",
     "Training delivery model: 70% role-based e-learning, 30% instructor-led.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Go-live scorecard",
     "Standard go-live scorecard: 12 operational KPIs.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Migration data handling",
     "Migration data handling: client data processed only in client-controlled environments.",
     "Delivery Excellence Lead", _V, _R, None),
    ("Reference: regional health system ERP",
     "ERP implementation for a seven-hospital regional health system (~11,000 "
     "employees) completed 2025; won; go-live on schedule; reference approved.",
     "Practice Lead", _V, _R, _MERIDIAN),
    ("Reference: payroll parallel cycles",
     "Payroll parallel runs at a seven-hospital regional health system: four "
     "cycles, zero variance at the final cycle.",
     "Practice Lead", _V, _R, _MERIDIAN),
    ("Reference: legacy system retirement",
     "24 legacy systems retired at a seven-hospital regional health system.",
     "Practice Lead", _V, _R, _MERIDIAN),
    ("Reference: patient and financial record migration",
     "Patient and financial record migration for a two-campus community medical "
     "center (~4,200 employees) completed 2024; reconciliation gates passed; "
     "reference approved.",
     "Practice Lead", _V, _R, _CASCADE),
    ("Reference: clinical interface cutover",
     "Clinical interface integration at a two-campus community medical "
     "center: 12 interfaces cut over.",
     "Practice Lead", _V, _R, _CASCADE),
    ("Reference: municipal utility ERP + HCM",
     "ERP and HCM implementation for a municipal utility (~1,840 employees, "
     "unionized workforce), won 2024; hypercare exited in five weeks.",
     "Practice Lead", _V, _R, _BLUEGRASS),
    ("Reference: school district training rollout",
     "Implementation for a K-12 public school district (~3,100 employees), "
     "2023; training delivered to 1,800 end users.",
     "Practice Lead", _V, _R, _TALLGRASS),
    ("Reference: insurer engagement — not available",
     "Finance and supply-chain engagement for a regional property-and-casualty "
     "insurer (~2,600 employees), 2023; lost at final stage; reference NOT "
     "available.",
     "Practice Lead", _V, _R, _HARBORLIGHT),
    ("Regional delivery center",
     "Regional delivery center (Columbus) staffed 24/7 during hypercare.",
     "Support Lead", _V, _R, None),
    ("On-site response SLA",
     "4-hour on-site response SLA within the region.",
     "Support Lead", _V, _R, None),
    ("Hypercare window",
     "Standard hypercare window: six weeks post-go-live.",
     "Support Lead", _V, _R, None),
    ("Sev-1 response commitment",
     "Sev-1 response: 30 minutes, 24/7 during hypercare.",
     "Support Lead", _V, _R, None),
    ("Sev-2 response commitment",
     "Sev-2 response: 4 business hours.",
     "Support Lead", _V, _R, None),
    ("LAPSED: prior-platform credential count",
     "18 certified consultants on the prior platform version.",
     "Practice Lead", "2024-11-15", "2025-11-01", None),  # lapsed BY DESIGN (D6)
]

DEMO_CANON_ID = "kb_canontrn001"
DEMO_CANON_BODY = (
    "Our training program prepares clinical and back-office staff before "
    "go-live through hands-on practice environments, quick-reference guides "
    "refreshed at each release, and floor support through the first "
    "production weeks."
)
DEMO_RESTRICTED_ID = "kb_restrsev001"


def _fact_cards():
    for n, (title, fact, owner, verified, review_due, client) in enumerate(
            FACT_SHEET, start=1):
        card = {
            "kb_id": f"kb_fact{n:06d}",
            "layer": "fact_sheet",
            "doc_kind": "fact",
            "title": title,
            "summary": fact,
            "claim_tier_max": 1,
            "owner": owner,
            "verified_date": verified,
            "review_due": review_due,
        }
        provenance = {"source_pursuit": "pur_fact_sheet_seed",
                      "date": verified, "ingested_by": "steward"}
        identifiers: dict[str, str] = {}
        if client:
            provenance["source_client"] = client
            identifiers = {client: "CLIENT"}
        yield card, fact, provenance, identifiers


def seed_curated(store: KBStore) -> None:
    """Fact sheet + one canonical-block card + one use_restriction card —
    committed-store properties, not test plants (B34(26))."""
    for card, body, provenance, identifiers in _fact_cards():
        store.write_card(card, body, provenance, identifiers)
    store.write_card(
        {"kb_id": DEMO_CANON_ID, "layer": "corpus", "doc_kind": "section_exemplar",
         "title": "End-user training approach for clinical and back-office staff",
         "summary": ("Approved boilerplate: end-user training approach for "
                     "clinical and back-office staff at go-live."),
         "section_types": ["training"],
         "canonical_block": True, "use_restriction": False, "outcome": "won"},
        DEMO_CANON_BODY,
        {"source_pursuit": "pur_curated_seed", "date": "2026-06-01",
         "ingested_by": "steward"},
        {},
    )
    store.write_card(
        {"kb_id": DEMO_RESTRICTED_ID, "layer": "corpus", "doc_kind": "past_response",
         "title": "Issue escalation ladder and severity management runbook",
         "summary": ("Escalation ladder and severity management approach from "
                     "a named engagement; reuse restricted (D2)."),
         "section_types": ["support_model"],
         "use_restriction": True, "outcome": "won"},
        ("Severity ladder with named response windows, escalation contacts "
         "per tier, and a weekly review cadence, developed for a specific "
         "engagement and not reusable as boilerplate."),
        {"source_pursuit": "pur_curated_seed", "source_client": _HARBORLIGHT,
         "date": "2026-06-01", "ingested_by": "steward"},
        {_HARBORLIGHT: "CLIENT"},
    )


def ingest_corpus(kb_root, script=None) -> tuple[KBStore, list[IngestReport]]:
    """Deterministic scripted ingest of the whole corpus + the curated layer
    — the shared setup for the P2 acceptance tests and the seed CLI."""
    store = KBStore(kb_root)
    runs = store.root / "runs"
    existing = sorted(p.name for p in runs.iterdir()) if runs.exists() else []
    log = RunLogger(store.root, f"run_{len(existing) + 1:04d}", "kb")
    caller = TracedCaller(FakeCaller(script or SCRIPT), log)
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=effective_config(), kb_snapshot=store.snapshot())
    reports = [ingest_document(store, caller, log, doc) for doc in SOURCE_DOCS]
    log.run_end(status="completed")
    seed_curated(store)
    return store, reports
