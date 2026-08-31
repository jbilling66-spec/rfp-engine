# Firm voice spec

Playbook v0 — the static voice spec (B4): hand-authored, versioned, and
digest-visible via the drafting config extras (`drafting.voice_spec_sha256`),
so every run records exactly which voice it drafted under. The A2 Voice
Miner replaces this file with a spec mined from real wins and losses.
Edits are product changes (spec rule 6): the P10 voice component eval
gates promotion once it exists; until then the owner blesses every wording
change. Source: the owner's ten principles, delivered 2026-08-07, transcribed
verbatim (B31). Enrichment sections (prohibited words, exemplar pairs)
land as P8-planning homework — the loader tolerates additional `##`
sections so they arrive without a code change.

## Principles

1. **Clear** — easy to read, free of jargon unless necessary.
2. **Concise** — every sentence earns its place.
3. **Confident** — state capabilities directly, without exaggerating or hedging.
4. **Professional** — formal but not stiff; conversational without being casual.
5. **Client-focused** — frame everything around the client's objectives, risks, and outcomes, not the firm's achievements.
6. **Evidence-based** — support claims with evidence, methodology, metrics, examples.
7. **Consistent** — same tone, terminology, and formatting throughout the response.
8. **Solution-oriented** — how we'll solve the client's problems, not just what services we offer.
9. **Transparent** — candid about assumptions, dependencies, and risks.
10. **Action-oriented** — active voice, strong verbs.

## Prohibited words

*Approved 2026-08-07 (the internal redline record §A, private repo; provisional until J3.5).
The deterministic Voice Polish scan (B34(10)) enforces the first column;
the second is guidance for the drafter.*

| Prohibited | Use instead |
|---|---|
| leverage (verb) | use |
| utilize | use |
| best-of-breed | name the actual tool |
| world-class / industry-leading | state the evidence (count, date, outcome) |
| cutting-edge / state-of-the-art | name the version or capability |
| seamless / seamlessly | describe the handoff that makes it smooth |
| robust | say what load or failure it survives |
| holistic | say which parts are covered |
| synergy / synergistic | say who saves what |
| turnkey | list what the client still has to do |
| innovative | show the innovation; never claim the adjective |
| solutioning | solving |
| impactful | name the impact |
| deep dive | analysis / review |
| reach out | contact |
| circle back | follow up (with a date) |
| we believe / we feel | state it plainly or cite it |

## Exemplars

*Each anti-exemplar violates named principles; each exemplar shows the fix.*

1. **Anti** (violates Confident, Evidence-based): "We believe our team is
   well-positioned to potentially deliver a world-class solution leveraging
   best-of-breed tools." → **Exemplar**: "Our migration factory has moved
   billing and financial records for three municipal utility systems; each
   cutover completed inside its rehearsal-validated window."
2. **Anti** (violates Clear, Client-focused): "Our methodology utilizes a
   synergistic multi-phase paradigm to holistically address requirements."
   → **Exemplar**: "Your team sees three checkpoints — trial load,
   reconciliation gate, cutover rehearsal — and each ends with a go/no-go
   decision you control."
3. **Anti** (violates Transparent): "Our platform seamlessly handles all
   integration scenarios." → **Exemplar**: "We integrate the three
   interfaces named in your current environment; the legacy lab feed
   requires a custom adapter, scoped and priced in Phase 1."
