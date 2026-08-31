# The P12 extraction-gate container (B51) — and the seed of the A5 runtime.
#
# Native-arch Linux with current CPU torch: the §A2 gate, the docling-eval
# benchmark runs, and the p95 verdict all execute here, never on the host.
# The original build pinned linux/amd64 because the first build host was an
# Intel Mac (its only native docling path was an abandoned torch 2.2.2 pin);
# that machine died 2026-08-17..20 and the pin died with its rationale —
# B54: the replacement host is Apple Silicon, where amd64 means Rosetta
# emulation for multi-day benchmark runs. The platform pin is dropped, the
# extraction lock is re-frozen from the arm64 image, and the A5 target
# (Azure, amd64) inherits a WIDENED same-image re-check: B51's p95 caveat
# plus a full amd64 rebuild+gate rerun at the lift (quality metrics are
# hardware-independent; the recorded DP-Bench/FinTabNet numbers stand).
#
#   make gate-image        build + freeze requirements-extraction.lock
#   make extraction-models weights download (the one deliberately-online step)
#   make gate              the §A2 run, --network none (the outer wall)
FROM python:3.11-slim

# Offline-by-default is baked into the image, not remembered by callers:
# network-enabled steps override these explicitly; a production-mode run
# never does (spec §A3 — no runtime fetch from a public hub, ever).
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /work

# Dependencies layer-cache against pyproject alone: the repo mounts at
# runtime (-v), so code edits never rebuild torch. The stub engine package
# exists only to let pip resolve the project's dependency set; the project
# itself is uninstalled and the mounted /work supplies the real code.
# CPU wheels via the pytorch index — the CUDA bundle is dead weight on a
# no-GPU target and the kill criterion is written "without a GPU".
COPY pyproject.toml ./
# RapidOCR pulls GUI opencv, whose mesa/X11 system libs slim lacks (and
# whose apt layer corrupted the first rebuild's export); this container
# has no display — headless cv2 is the same API with zero system deps.
# The pip cache is a build-cache mount: a CDN stall two hours in (it
# happened) costs a retry, not a fresh 1.5GB download; the image itself
# stays cache-free.
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p engine && touch engine/__init__.py && \
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 \
    PIP_RETRIES=5 PIP_DEFAULT_TIMEOUT=120 \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        ".[extraction,dev]" docling-eval protobuf onnxruntime && \
    pip uninstall -y rfp-engine-v2 opencv-python && \
    pip install --no-deps opencv-python-headless && \
    rm -rf engine pyproject.toml

# Lets the dependency-seam test assert presence instead of absence here.
# torch.compile wants a C++ toolchain the slim image deliberately lacks
# (run-2 finding: InvalidCxxCompiler killed every PDF conversion) —
# eager mode is a no-op fallback with identical outputs; p95 is measured
# eager, which is the conservative side of the bar.
ENV RFP_GATE_CONTAINER=1 \
    TORCH_COMPILE_DISABLE=1 \
    TORCHDYNAMO_DISABLE=1

CMD ["python", "-c", "import docling; print('extraction-gate ready; docling', docling.__version__)"]
