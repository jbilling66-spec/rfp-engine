"""The committed seed store (kb/) is a golden: a fresh scripted ingest of
the fixture corpus must reproduce it byte-for-byte (the twins drift-test
pattern). Timestamped files (kb/runs/, restricted/access.jsonl) are
gitignored local evidence and deliberately outside the comparison.
"""

from pathlib import Path

from tests.kb.fixtures.corpus import ingest_corpus

REPO_KB = Path(__file__).resolve().parents[2] / "kb"


def _tree_bytes(root: Path, sub: str, glob: str) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((root / sub).glob(glob))}


def test_committed_seed_store_matches_fresh_ingest(tmp_path):
    fresh, reports = ingest_corpus(tmp_path / "kb")
    assert all(r.status == "ingested" for r in reports)
    for sub, glob in (("cards", "*.md"),
                      ("restricted/provenance", "*.json"),
                      # P13: the L1 canonical models and the retained L0
                      # sources join the golden — same drift discipline.
                      ("canonical", "*.json"),
                      ("restricted/sources", "*")):
        committed = _tree_bytes(REPO_KB, sub, glob)
        rebuilt = _tree_bytes(fresh.root, sub, glob)
        assert committed == rebuilt, (
            f"kb/{sub} drifted from a fresh corpus ingest — if the fixture "
            f"change is intentional, re-run `python -m engine kb seed` and "
            f"commit the store in the same change"
        )


def test_committed_seed_store_has_expected_shape():
    cards = list((REPO_KB / "cards").glob("*.md"))
    assert len(cards) >= 20
    assert len(list((REPO_KB / "restricted" / "provenance").glob("*.json"))) == len(cards)
