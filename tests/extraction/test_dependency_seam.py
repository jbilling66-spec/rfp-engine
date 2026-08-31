"""The dependency seam is a property, not a discipline (C1, B51).

Two directions: every module the conftest would deselect must exist on
disk (a rename reddens here rather than silently dropping out of the
gate), and docling's presence must match the environment's claim —
absent in the main venv, present inside the gate container.
"""

import importlib.util
import os
from pathlib import Path

from tests.extraction.seam import DOCLING_ONLY_MODULES

HERE = Path(__file__).parent


def test_every_deselected_module_exists_on_disk():
    for name in DOCLING_ONLY_MODULES:
        assert (HERE / name).is_file(), (
            f"seam roster names {name!r} but no such file exists — renamed "
            "without updating tests/extraction/seam.py; the gate container "
            "would silently lose that coverage"
        )


def test_docling_presence_matches_the_environment_claim():
    have = importlib.util.find_spec("docling") is not None
    if os.environ.get("RFP_GATE_CONTAINER"):
        assert have, (
            "RFP_GATE_CONTAINER is set but docling is not importable — the "
            "gate image no longer carries its own dependency"
        )
    else:
        assert not have, (
            "docling leaked into the main venv — extraction runs only in "
            "the gate container (B51); `make check` must stay torch-free"
        )
