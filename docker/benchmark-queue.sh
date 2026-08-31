#!/bin/bash
# P12 C6 benchmark queue — B54 full-redo form (2026-08-20): the Intel host
# died mid-queue and took benchmarks/ with it; per the owner's full-redo decision
# every stage re-runs on the replacement machine (native arm64 image):
#
#   DPBench -> OmniDocBench -> DocLayNetV1 -> FinTabNet -> PubTabNet
#
# Order is shortest-first: DP-Bench (~1h on the old host) smoke-tests the
# rebuilt stack end-to-end before any multi-day stage starts, and the two
# ~20h TableFormer stages run last. OmniDocBench results are
# QUARANTINED per B52: auxiliary grading tool only, excluded from the §A2
# adoption reasoning, recorded in a marked section of external-benchmarks.md.
#
# Launch (host, survives the session):
#   mkdir -p benchmarks/logs
#   nohup caffeinate -ims docker/benchmark-queue.sh > benchmarks/logs/queue.log 2>&1 &
#
# Halt semantics: any stage that fails its artifact check (evaluation JSONs
# on disk) or shows the upstream "Saved 0 records" silent-failure signature
# writes benchmarks/logs/QUEUE_HALTED with the reason and stops the queue —
# nothing cascades onto a broken stage. Verdicts come from artifacts and
# logs, never exit codes (docling-eval has exited 0 over a 100% failed run).
#
# 2026-08-16 fix: `evaluate` nests its JSON under
# <output-dir>/evaluations/<modality>/ — the original shallow glob
# (<output-dir>/evaluations/*.json) false-halted the queue on a fully
# successful FinTabNet run. Artifact checks now find recursively.
#
# FinTabNet resume, if its run died (chunk-resumable; container was launched
# with AutoRemove so only this record and the host log survive it):
#   docker run --rm -v "$PWD:/work" -w /work \
#     -e DOCLING_ARTIFACTS_PATH=/work/models/docling \
#     -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
#     rfp-extraction-gate sh -c \
#     'docling-eval create --benchmark FinTabNet --output-dir benchmarks/fintabnet --prediction-provider TableFormer && \
#      docling-eval evaluate --benchmark FinTabNet --modality table_structure --input-dir benchmarks/fintabnet/eval_dataset --output-dir benchmarks/fintabnet/evaluations'

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$REPO/benchmarks/logs"
IMG="rfp-extraction-gate"
MIN_FREE_GB=60
mkdir -p "$LOGDIR"

note() { echo "[queue $(date '+%F %T')] $*"; }

halt() {
  note "HALT: $*"
  echo "$(date '+%F %T') $*" > "$LOGDIR/QUEUE_HALTED"
  exit 1
}

free_gb() { df -g "$REPO" | awk 'NR==2 {print $4}'; }

# --- Stage 0: weights must verify against the committed manifest before any
# stage runs — the B54 rebuild re-downloaded models/ and the digests are the
# continuity proof between the recorded runs and this redo ---
if docker run --rm -v "$REPO:/work" -w /work "$IMG" \
     python -m engine.extraction.weights verify >> "$LOGDIR/weights-verify.log" 2>&1; then
  note "weights verified against config/extraction-models.json — proceeding"
else
  halt "weights failed digest verification — read $LOGDIR/weights-verify.log; do not benchmark on unverified weights"
fi

# run_stage NAME OUTDIR CMD — runs CMD in the gate container (network on: HF
# dataset download is part of create), tees to its own log, verifies by
# artifacts. Transient network failures (HF 429 rate limits, timeouts — one
# killed the first OmniDocBench attempt 2026-08-16) get MAX_ATTEMPTS tries
# with RETRY_WAIT_S between them; create is chunk-resumable so a retry
# resumes, never restarts. The "Saved 0 records" signature halts immediately
# (deterministic env bug — retrying it wastes hours). If HF_TOKEN is set on
# the host it is passed through for authenticated (higher) rate limits.
MAX_ATTEMPTS=3
RETRY_WAIT_S=900
run_stage() {
  local name="$1" outdir="$2" cmd="$3"
  local stage_log="$LOGDIR/$name.log"
  local attempt gb
  # Relaunch-idempotent (B54 OOM halt taught this): a stage whose evaluation
  # JSONs already exist is complete — a halted queue relaunches without
  # re-running finished stages. Artifacts are the verdict, same as ever.
  if find "$REPO/$outdir"/evaluations -name '*.json' 2>/dev/null | grep -q .; then
    note "$name already complete ($(find "$REPO/$outdir"/evaluations -name '*.json' | wc -l | tr -d ' ') evaluation JSONs) — skipping"
    return 0
  fi
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    gb=$(free_gb)
    if [ "$gb" -lt "$MIN_FREE_GB" ]; then
      halt "$name: only ${gb}GB free (< ${MIN_FREE_GB}GB guard) — refusing to download"
    fi
    note "starting $name attempt $attempt/$MAX_ATTEMPTS (${gb}GB free) — log: $stage_log"
    docker run --rm -v "$REPO:/work" -w /work \
      -e DOCLING_ARTIFACTS_PATH=/work/models/docling \
      -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
      ${HF_TOKEN:+-e HF_TOKEN="$HF_TOKEN"} \
      "$IMG" sh -c "$cmd" >> "$stage_log" 2>&1
    note "$name container exited — checking artifacts"
    if grep -q "Saved 0 records" "$stage_log"; then
      halt "$name: 'Saved 0 records' signature in $stage_log (upstream exits 0 on this — the log is the verdict)"
    fi
    if find "$REPO/$outdir"/evaluations -name '*.json' 2>/dev/null | grep -q .; then
      note "$name complete: $(find "$REPO/$outdir"/evaluations -name '*.json' | wc -l | tr -d ' ') evaluation JSON(s)"
      return 0
    fi
    if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
      note "$name attempt $attempt failed artifact check — waiting ${RETRY_WAIT_S}s then retrying (resume, not restart)"
      sleep "$RETRY_WAIT_S"
    fi
  done
  halt "$name: no evaluation JSONs after $MAX_ATTEMPTS attempts — read $stage_log"
}

# --- Stage: DP-Bench (B54 redo) — the Stage-1 re-derivation and the rebuilt
# stack's smoke test; same 4-modality pattern as the recorded run ---
run_stage "dpbench" "benchmarks/dpbench" "
  docling-eval create --benchmark DPBench --output-dir benchmarks/dpbench --prediction-provider Docling &&
  for m in table_structure markdown_text reading_order layout; do
    docling-eval evaluate --benchmark DPBench --modality \$m \
      --input-dir benchmarks/dpbench/eval_dataset \
      --output-dir benchmarks/dpbench/evaluations \
      || echo \"[queue-warn] DPBench evaluate \$m failed\";
  done"

# --- Stage: OmniDocBench (QUARANTINED per B52) — 4 modalities, per-modality
# evaluate failures logged and tolerated; the artifact check requires >=1 JSON ---
run_stage "omnidocbench" "benchmarks/omnidocbench" "
  docling-eval create --benchmark OmniDocBench --output-dir benchmarks/omnidocbench --prediction-provider Docling &&
  for m in table_structure markdown_text reading_order layout; do
    docling-eval evaluate --benchmark OmniDocBench --modality \$m \
      --input-dir benchmarks/omnidocbench/eval_dataset \
      --output-dir benchmarks/omnidocbench/evaluations \
      || echo \"[queue-warn] OmniDocBench evaluate \$m failed\";
  done"

# --- Stage: DocLayNetV1 — layout ---
run_stage "doclaynet" "benchmarks/doclaynet" "
  docling-eval create --benchmark DocLayNetV1 --output-dir benchmarks/doclaynet --prediction-provider Docling &&
  docling-eval evaluate --benchmark DocLayNetV1 --modality layout \
    --input-dir benchmarks/doclaynet/eval_dataset \
    --output-dir benchmarks/doclaynet/evaluations"

# --- Stage: FinTabNet.c (B54 redo) — the Stage-2 re-derivation; ~20h class,
# chunk-resumable create so a retry resumes ---
run_stage "fintabnet" "benchmarks/fintabnet" "
  docling-eval create --benchmark FinTabNet --output-dir benchmarks/fintabnet --prediction-provider TableFormer &&
  docling-eval evaluate --benchmark FinTabNet --modality table_structure \
    --input-dir benchmarks/fintabnet/eval_dataset \
    --output-dir benchmarks/fintabnet/evaluations"

# --- Stage: PubTabNet — val split (test ground truth was never published).
# evaluate MUST repeat --split val: it defaults to test and dies on "no
# data" over a fully successful create (sixth run-mechanics finding,
# 2026-08-22 — three 8h prediction runs reached evaluate before the
# one-flag fix; predictions were chunk-saved, nothing lost) ---
run_stage "pubtabnet" "benchmarks/pubtabnet" "
  docling-eval create --benchmark PubTabNet --split val --output-dir benchmarks/pubtabnet --prediction-provider TableFormer &&
  docling-eval evaluate --benchmark PubTabNet --modality table_structure --split val \
    --input-dir benchmarks/pubtabnet/eval_dataset \
    --output-dir benchmarks/pubtabnet/evaluations"

note "queue complete — all stages have evaluation JSONs; extract numbers from the logs/JSONs, never the exit codes"
