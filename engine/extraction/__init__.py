"""Document-extraction layer (P12/WP12, B51).

Vocabulary (B44): "document extraction" is this parse layer; "claim
extraction" is the eval suite measuring the auditor. Two unrelated
subsystems, one word — always qualify.
"""

# Moves whenever this layer's own behavior changes; a component of the
# extraction fingerprint (C12), never of config_digest — the eval
# baselines must not stale for a subsystem their measures never touched.
EXTRACTOR_VERSION = "0.1.0"
