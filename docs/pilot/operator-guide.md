# The pilot operator guide

*Audience: the people running pursuits through the workbench during the
pilot — no engineering background assumed. Bold marks text exactly as it
appears on the screen: every bold phrase in this guide appears verbatim in
the web app's source files — that is what the drift test checks, and no
more (`tests/contracts/test_pilot_docs.py`; behavior itself is described in
prose the test does not parse). Backticked doors in the "Steps the pilot host runs
for you" section are checked against the door index (docs/graph/doors.md)
the same way.*

## What this is

The RFP Engine is a drafting workbench: you feed it an RFP package, it
reads the package, researches against the firm's knowledge base, and
drafts a response — and it stops for a human decision at every gate. It
never sends anything to a buyer; it is an internal drafting assistant with
mandatory human review before any external submission. Nothing you do in
the workbench spends money on model calls during the pilot.

The workbench runs only on the pilot machine — you use it at that machine,
in its browser. It is not on the internet, and there is no account system
beyond the name you give it.

## Signing in

When the app opens you will see **Who is deciding?** — type your name and
press **Start session**. Every decision and comment you make is recorded
under that name, so use your real one. If the sidebar shows
**not signed in**, press **declare operator** to bring the prompt back.

The sidebar has four tabs: **Pursuits** (the board you will live on),
**Knowledge base** (the firm's reusable answer library), **Assistant** (a
question-answering helper grounded in the docs and the library), and
**Telemetry** (system numbers; you can ignore it).

## Starting a pursuit

1. On the **Pursuits** board, press **+ New pursuit**.
2. Give it a short id (the screen shows the expected shape) and press
   **Create**.
3. On the pursuit's detail screen, press **upload to inbox** and add the
   RFP workbook (.xlsx). You can also upload an optional ramble.md (your
   voice notes about the deal) and an optional research-pack.md.

## Advancing — and the pause

Press **Advance** to run the engine as far as it can go. It stops honestly:
at a gate that needs your decision, or on gaps that need answers. A status
strip narrates what is happening.

*The pause is normal.* During the pilot, the engine's judgment steps are
answered by an assistant session that the pilot host runs on the same machine. When
you press **Advance**, the app may sit quietly for a while at each judgment
step while that session answers. You do not need to do anything — wait for
the strip to move on.

If a run ends with a *refused* message about an unanswered call, the
answering session was not running. Tell the pilot host, and once it is running press
**Advance** again — nothing is lost, the engine picks up where it stopped.

## The three gates

Buttons appear only when the engine is actually waiting on that decision:

- **Review intake (Gate 0)** — confirm the engine read the package
  correctly before any research happens. Corrections rewrite the brief;
  open questions never block (you can mark **skip** on any of them).
- **Decide Gate 1** — the brief and win themes. You can mark **kill** on a
  theme that is wrong for the deal. **Approve** or **Reject** with notes;
  rejecting sends it back for a redo with your feedback.
- **Decide Gate 2** — the pursuit plan. You can mark **waive** on a gapped
  outline item. Approving freezes the plan.

A pursuit never moves past a gate by itself, and the engine never invents
content where the knowledge base is empty — those become gaps for a human
to answer.

## Review and revision

When drafting is done, press **Open review**. Read each section; press
**Comment** to attach feedback to a section. When your comments are in,
press **Revise (apply pending)** — the engine applies the pending comments
and produces the next revision. Repeat until it reads right.

## The knowledge base tab

The **Knowledge base** tab is the firm's answer library. You can search
and read it; **Export workbook** downloads it as a spreadsheet. Proposed
additions wait in an inbox at the top with **accept** and **reject**
buttons — accepting is a real change to the library, so if you are unsure,
leave it for the pilot host.

The **Assistant** tab answers questions about the library, the process, or
a pursuit — type a question and press **Send**. It reads and proposes;
every change it drafts waits for a human review, and nothing it does goes
to a buyer.

## Steps the pilot host runs for you

Some finishing steps have no button in the app yet — the pilot host runs them
directly against the engine and hands you the result:

- Rendering the submission documents: `POST /api/pursuits/{pursuit_id}/export`
- Listing what may go to the buyer: `GET /api/pursuits/{pursuit_id}/downloads`
- Fetching one file: `GET /api/pursuits/{pursuit_id}/download/{name:path}`
- Filling the buyer's own forms: `POST /api/pursuits/{pursuit_id}/writeback/confirm`
- A guest review link for someone outside the pilot: `POST /api/pursuits/{pursuit_id}/share`

Ask the pilot host when a pursuit reaches the point of producing files.

## The ground rules

The pilot runs under the build side's standing laws. Two of them govern
what you may put into the workbench, quoted from their source so they stay
word-for-word true here:

> "Synthetic data only, until A1." — "No real client names, fees, people,
> or documents anywhere" — fixtures, tests, prompts, sample data.

In plain terms: until the pilot host says the real-data gate is open, everything you
upload or type into the workbench is practice material — public documents,
invented names, sanitized text. No real client's name, numbers, people, or
files. If you are unsure whether something counts, it does — ask the pilot host
first. The same goes the other way: nothing the workbench produces goes to
a real buyer during the pilot.
