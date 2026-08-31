# P11 diagnostic run — cost actuals (2026-08-11)

One live run, both model-scored suites, owner-approved at the P11 gate.
Estimate given at the gate: **$2.95 ± 0.05**. Actual: **$2.9912**.

| suite | run | calls | cost USD | agent split |
|---|---|---|---|---|
| claim_extraction | `run_0006` | 31 | 0.7489 | claim_auditor 21, claim_verifier 10 |
| poison | `run_0007` | 108 | 2.2423 | claim_auditor 60, claim_verifier 48 |
| **total** | | **139** | **2.9912** | |

Guard headroom: `SpendBudget` $50.00 / 400 calls — never approached.
Reconciles with the CLI's reported `spend this invocation: $2.9912 over 139 calls`.

Prior cycles for comparison (the p10 close's cost record, private repo):
cX cycle 1 $2.9818 / 138 calls; cX cycle 2 $2.9415 / 135 calls.
