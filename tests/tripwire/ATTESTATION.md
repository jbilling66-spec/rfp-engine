# Tripwire attestation — the empty-list posture, stated on the record

This repository runs the tripwire with no restricted-token list: we accept
that only the synthetic probe is scanned for, and we will create
tripwire-local/tokens.txt before any restricted name exists.

That sentence is load-bearing: `tests/tripwire/tokens.py` honors this file
only when it appears verbatim. What it means in practice:

- The scans still run — every tracked file, every extracted binary, all
  git history, commit metadata — and still prove they can fail (the
  committed probe). They just have no real names to look for yet.
- **Before your organization's first real client name, engagement, or
  restricted term touches ANY file here**, create
  `tripwire-local/tokens.txt` (one token per line, `#` comments allowed —
  it is gitignored, machine-local by design). A local list always
  overrides this attestation.
- Committing a token list would itself be the disclosure the tripwire
  exists to prevent. Never track it; feed it.
