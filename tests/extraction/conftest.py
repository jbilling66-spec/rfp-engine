"""Dependency seam for the extraction tests (C1, B51).

docling is a container-only dependency: the offline suite (`make check`)
runs in .venv, which never installs it, and the docling-marked modules
are deselected here via collect_ignore — never skipped — so the suite
keeps its zero-skip property (B49). Inside the gate container
(`make gate`) docling is importable and the same modules collect and run.
"""

import importlib.util

from tests.extraction.seam import DOCLING_ONLY_MODULES

collect_ignore = (
    [] if importlib.util.find_spec("docling") else list(DOCLING_ONLY_MODULES)
)
