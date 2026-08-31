"""20 sample questions for the card-search acceptance clause.

Each question pairs with a MARKER — a phrase unique to the body of exactly
one card in the seeded corpus — because kb_ids are content-derived hashes
the fixture cannot hardcode. Tests resolve marker → kb_id against the
built store, then assert that kb_id lands in the top-K returned cards.
"""

QUESTIONS = [
    ("How do you structure a two-wave ERP cutover with payroll parallel "
     "gates and go/no-go criteria?", "rollback rehearsal"),
    ("How many mock conversions do you run and how are conversions "
     "reconciled?", "hash totals"),
    ("What is your integration approach for HL7 and FHIR interfaces on a "
     "hospital ERP?", "FHIR"),
    ("What are your interface testing passes and exit criteria?",
     "thirty days of production message"),
    ("How do you blend onshore and offshore staffing on an ERP program?",
     "offshore build pod"),
    ("What sprint cadence and decision log mechanics does your PMO use?",
     "ten business days"),
    ("How is program governance tiered between workstreams and executive "
     "steering?", "biweekly program board"),
    ("How do super-users and role-based training curricula drive adoption?",
     "teach-the-workflow"),
    ("How is fixed-fee pricing structured with a contingency pool?",
     "contingency pool"),
    ("How do you enforce segregation of duties and access recertification?",
     "segregation-of-duties"),
    ("How did you rebuild month-end close reporting with a governed "
     "semantic layer?", "semantic layer"),
    ("What does your hypercare command center look like after go-live?",
     "command center"),
    ("How do you run payroll parallel testing to a net-pay match for a "
     "unionized utility?", "net-pay matches"),
    ("How do you classify and sequence utility interfaces for cutover?",
     "punch-outs"),
    ("What does a sixteen-month milestone timeline with entry and exit "
     "criteria look like?", "dress rehearsal"),
    ("Which risks sink utility ERP programs and how are mitigations "
     "proven?", "risk register"),
    ("How do you frame an executive summary for a K-12 district ERP "
     "replacement?", "state-supported legacy finance"),
    ("What small named-team staffing works for a school district "
     "implementation?", "conversion specialist"),
    ("How do you migrate district position-control history and "
     "state-mandated account codes?", "step-and-lane"),
    ("How do you test state-mandated reporting exports against legacy "
     "submissions?", "transparency files"),
]
