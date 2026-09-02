# Review and revision

The **review surface** shows each section's text with marks: a colored
chip plus a one-line reason for every audited claim and finding. Open
**detail** under any mark for the full forensic record. BLOCK marks
stop packaging until revised or waived.

Type a comment under a section and press **Comment** — it pends until
the next revision round (the pending note under the section shows it).
**Revise (apply pending)** runs the round: the revision agent applies
comments and validation directives, replies to each comment, and only
the touched sections are re-audited. Every round is on the record and
readable through the revision doors (`GET /api/pursuits/{pursuit_id}/revisions`
lists the rounds; `GET /api/pursuits/{pursuit_id}/revisions/{n}` carries one
round's before/after diff); the workbench does not render that history
yet — the history panel is wave 2 of the workbench work.

After a round, each section the agent rewrote offers **Accept revision**
and **Reject revision**; a pending comment of your own can be taken back
with **Withdraw**. A BLOCK mark offers **Waive** — the reason you give at
**Confirm waiver** is the record.

Answered gaps are drafted at the next revision round. When everything
is right, **Accept pursuit** closes the review — it refuses while
packaging is blocked.
