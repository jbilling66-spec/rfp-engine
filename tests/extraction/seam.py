"""The docling-only module roster (C1, B51).

Module filenames in this directory that import docling at module level.
The conftest deselects them (collect_ignore — never a skip) when docling
is absent, i.e. everywhere except the gate container; the seam test
asserts every name here exists on disk, so a rename reddens the suite
instead of silently shrinking the gate's coverage.

Container-only includes PIL-only: PIL ships with docling, and
find_spec("docling") is the container detector.

Grown by later P12 commits (C9's backend tests land here).
"""

DOCLING_ONLY_MODULES: list[str] = [
    "test_corpus_container.py",  # C4: build_scanned_pdf needs PIL
    "test_worker_container.py",  # C9: production seam against real docling
    "test_media_container.py",  # C11: figure plumbing (see its evidence-limit note)
]
