PY := .venv/bin/python
GATE_IMAGE := rfp-extraction-gate

.PHONY: check slice eval lock gate-image extraction-models weights-verify gate-tests gate public-cut

# Offline suite — FakeCaller only, zero model spend. The phase-gate command.
check:
	$(PY) -m pytest -q

# Build + verify the fresh-history public mirror in a staging dir (P22,
# B85): allowlist export via git plumbing, residue scan, one neutral
# commit, full suite green in staging. Prints the manual push steps —
# the push itself is the owner's act, never this target's.
public-cut:
	$(PY) tools/public_cut.py

# M1 vertical slice (P8, B34(24)): demo package end-to-end, headless, zero
# spend. Invokes the CLI runner ITSELF — the surface ships with its own
# liveness proof. The one RFP_LIVE=1 milestone run uses `slice --live`.
slice:
	$(PY) -m engine slice --ci --fresh --workspace pursuits/slice-ci

# Eval harness + release gates (lands at P10).
# Writes the release record and exits nonzero while a blocking bar is
# unmet — RED here is the honest state until the owner-gated live
# re-baseline close step (B40/D4/D6), not a breakage.
eval:
	$(PY) -m engine eval

# Re-pin the dependency lock after an intentional dependency change.
# uv-created venvs carry no pip module (B87 §2: `python -m pip` died
# there silently), so the freeze goes through uv against $(PY)'s env.
# P26a P0-12: a HASHED lock compiled from pyproject. The current lock is the
# constraint set, so `make lock` re-pins today's versions with hashes and never
# upgrades silently — a version move is a deliberate edit of the constraint
# (delete the old pin line first), reviewed as a diff, never a hand splice.
lock:
	cp requirements.lock .lock-constraint.tmp
	uv pip compile pyproject.toml --extra dev --generate-hashes \
	  --no-header --no-annotate --python $(PY) \
	  -c .lock-constraint.tmp -o requirements.lock; rm -f .lock-constraint.tmp

# P12 extraction gate (B51): container-first — the host never installs
# docling. Builds native-arch Linux (B54: amd64 pin dropped with the Intel
# host; A5 re-checks on amd64) with CPU torch and freezes the container's
# own Linux pins as the extraction lock. `extraction-models` and `gate`
# land with their modules (C3/C5) — a target naming code that does not
# exist yet is the B49/F-4 defect shape.
gate-image:
	docker build -f docker/extraction-gate.Dockerfile -t $(GATE_IMAGE) .
	{ echo "# Container-resolved record (Linux, CPU torch) — NOT installable from PyPI alone:"; \
	  echo "# the torch/vision +cpu pins resolve only with --extra-index-url https://download.pytorch.org/whl/cpu"; \
	  echo "# (see docker/extraction-gate.Dockerfile). Regenerated whole by \`make gate-image\`, never hand-edited."; \
	  docker run --rm $(GATE_IMAGE) pip freeze; } > requirements-extraction.lock

# Weights download (GB-scale — the one deliberately-online step), then the
# digest manifest the backend refuses to run without. `granitedocling` is
# the VLM the fabrication test diffs against the deterministic path (X3);
# its artifact id was named by the first real download (2026-08-15),
# closing the deferral this comment used to carry.
extraction-models:
	docker run --rm \
	  -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
	  -v "$(CURDIR)":/work -w /work $(GATE_IMAGE) \
	  sh -c "docling-tools models download -o models/docling \
	         && docling-tools models download granitedocling -o models/docling \
	         && python -m engine.extraction.weights freeze"

# Verify models/ against the COMMITTED digest manifest without touching it
# (B55: `extraction-models` ends in freeze, which overwrites the manifest —
# on a rebuilt machine, verify FIRST; a digest match is the continuity
# proof between recorded runs and the fresh download, and a mismatch is a
# finding, never an auto-refreeze). Same check the benchmark queue runs
# as its Stage 0.
weights-verify:
	docker run --rm -v "$(CURDIR)":/work:ro -w /work $(GATE_IMAGE) \
	  python -m engine.extraction.weights verify

# Container test leg WITHOUT re-rendering the gate verdict (C9): verifies
# weights and runs the extraction suite where docling exists — the roster
# modules the offline suite deselects. Use during C8-C13 build; `gate` is
# the one that writes report.json.
gate-tests:
	docker run --rm --network none \
	  -v "$(CURDIR)":/work -w /work $(GATE_IMAGE) \
	  sh -c "python -m engine.extraction.weights verify \
	         && python -m pytest tests/extraction -q"

# The §A2 run: network-disabled container (the outer wall on top of the
# C2 sandbox). Verifies weights, collects the container-only tests the
# offline suite deselects, then renders the gate verdict and writes
# docs/milestones/p12-extraction-gate/report.json for the C7 checkpoint.
gate:
	docker run --rm --network none \
	  -v "$(CURDIR)":/work -w /work $(GATE_IMAGE) \
	  sh -c "python -m engine.extraction.weights verify \
	         && python -m pytest tests/extraction -q \
	         && python -m engine.extraction.gate"
