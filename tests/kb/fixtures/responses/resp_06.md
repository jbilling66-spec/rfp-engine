# DOC:resp_06

## Security and Compliance

Harborlight Insurance Group's regulatory posture required SOC 2 Type II
alignment and state insurance-department audit readiness from day one. We
implemented role-based access with segregation-of-duties rules enforced at
the workflow level: no user could both create and approve a payment run,
and quarterly access recertification was automated with line-manager
attestation. All environment access ran through the client's identity
provider; no local accounts existed in any tier. Audit logging streamed to
Harborlight Insurance Group's SIEM with a documented retention schedule.

## Reporting and Analytics

We rebuilt the month-end close reporting stack on the platform's embedded
analytics rather than the legacy data warehouse, cutting close-cycle
reporting from nine days to four. Finance power users received a governed
semantic layer — conformed dimensions for entity, department, and program —
so ad hoc analysis no longer required IT tickets. The reporting workstream
was delivered within the $1,650,000 engagement fee. Reference contact:
Marcus Ellison, VP of Finance Transformation.
