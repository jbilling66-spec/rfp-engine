# The pilot operator guide

*Audience: the people running pursuits through the workbench during the
pilot — no engineering background assumed. Bold marks text exactly as it
appears on the screen: every bold phrase in this guide appears verbatim in
the web app's source files, and the guide names no door by route — that is
what the drift test checks, and no more (`tests/contracts/test_pilot_docs.py`;
behavior itself is described in prose the test does not parse). Everything
a reviewer or guest touches is a button; nothing in this guide needs a
terminal.*

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

When the app opens you will see **Who is deciding?** — type your name,
choose **Your role** (nothing is preselected — pick the role you are
acting in), and press **Start session**. Every decision and comment you
make is recorded under that name and role; the role sets the rate the
effort figures use, so choose honestly. If the sidebar shows
**not signed in**, press **declare operator** to bring the prompt back.

The sidebar has five tabs: **Pursuits** (the board you will live on),
**Pings** (questions routed to experts, across pursuits),
**Knowledge base** (the firm's reusable answer library), **Assistant**
(a question-answering helper grounded in the docs and the library), and
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

Each gate screen shows **Minutes on this gate** — the time you have had
it open, counted while the window is in front of you. Accept the figure
or type your own; it is recorded with your decision so the pilot can
say what human time a pursuit costs.

A pursuit never moves past a gate by itself, and the engine never invents
content where the knowledge base is empty — those become gaps for a human
to answer.

## Gaps and pings

On the pursuit screen, under **Gaps and pings**, every open gap has a
**Ping an SME** button: choose who it goes to (nothing is preselected)
and press it. To ask something the engine did not, pick a section,
type the question, and press **Open a gap**. The **Pings** tab lists
every routed question across pursuits, marked **escalated** after a
day unanswered; type the answer and press **Answer** — tick
**propose a KB card** to offer the answer to the knowledge base, where
the steward reviews it before it is ever reused.

## Review and revision

When drafting is done, press **Open review**. Read each section; press
**Comment** to attach feedback to a section. When your comments are in,
press **Revise (apply pending)** — the engine applies the pending comments
and produces the next revision. Repeat until it reads right. A pending
comment of your own can be taken back with **Withdraw** before the next
round; after a round, each section the engine rewrote offers
**Accept revision** or **Reject revision**, both on the record.

A red BLOCK mark stops the documents from going out until the claim is
revised or waived. Press **Waive** beside it, write the real reason, and
press **Confirm waiver** — the waiver is recorded under your name with
that reason, and a boilerplate reason is surfaced as a warning, never
hidden.

When it all reads right, press **Accept pursuit** — every drafted
section stamps final. It refuses while anything is still blocked.

## Sharing for outside review

Under **Share for review** on the pursuit screen, press
**New share link**, say who it is for, and choose how many days it lives;
press **Create link**. The link opens a read-only page of the review with a
comment box under every section — no sign-in, no internal panels.
**Copy link** puts it on your clipboard; **Revoke** kills it at once.
A guest's comment shows up under the section as a guest note; it
reaches the revision only if you press **Include** — press **Dismiss**
to record it without acting. Guests see the verdicts, never who waived
what or what anything cost.

The guest presses **Send comment** on the page they were sent, and sees
their own notes under **Your comments**.

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

## Finishing a pursuit

Once a pursuit has a validated draft, the pursuit screen shows
**Finish**:

- **Render documents** produces the submission and review documents and
  recomposes the record of what may go out.
- The downloads list under two headings and only two: **To the buyer**
  and **Internal — do not send**. Anything withheld says why, in the
  record's own words.
- **Preview write-back** shows exactly which cells of the buyer's own
  forms — or which sections of the firm's template — will be written and
  which are refused; nothing is written until you press
  **Confirm write-back** on that preview.
- **Complete by hand** opens the values only a person supplies on a
  firm-template response — the cover block (client, RFP title, dates,
  contact), the pricing grid (**Add row** for each milestone), the case
  block, the payment line. Press **Save values**; the next write-back
  lands them.

A firm-template response is a working copy first: it lists under the
internal heading, with the template's own instructions already stripped,
until every section has drafted prose and every hand-entered value is in.
Only then does the buyer copy appear under the buyer heading — a document
that still says "replace with the drafted section" never lists there.

When the buyer decides, press **Record outcome** on the pursuit screen —
the win and cost figures compute from that one entry.

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
