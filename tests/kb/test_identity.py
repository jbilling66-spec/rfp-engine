"""C6 (P13): content-anchored identity — the id moves only when the
content moves. The exact inverse of the pre-P13 whole-document hash,
whose one-byte-rotates-everything property silently orphaned
edit_survival through write_card_signals' unknown-id skip."""

from engine.kb.identity import (content_hash, identity_block, kb_id_for,
                                normalize, structural_key)

TEXT = ("The migration factory ran on schedule.\n"
        "It processed nine waves without a rollback.")


def test_id_stable_under_reflow():
    reflowed = ("  The   migration factory\nran on schedule. It processed "
                "nine waves without a rollback.  ")
    assert kb_id_for(TEXT) == kb_id_for(reflowed)
    assert kb_id_for(TEXT) == kb_id_for(TEXT.upper())


def test_distinct_content_distinct_ids():
    assert kb_id_for(TEXT) != kb_id_for(TEXT + " A tenth wave followed.")


def test_id_shape():
    kb_id = kb_id_for(TEXT)
    assert kb_id.startswith("kb_") and len(kb_id) == 13
    assert kb_id == "kb_" + content_hash(TEXT)[:10]


def test_id_ignores_everything_but_the_content():
    """Same chunk text in two different documents, positions, or
    orderings mints the SAME id — that is the dedup-by-construction
    property (one boilerplate, eleven sources, one card)."""
    assert kb_id_for(TEXT) == kb_id_for(TEXT)  # no doc, ordinal, or kind


def test_normalize_is_whitespace_and_case_only():
    assert normalize("A  B\n\tC") == "a b c"
    assert normalize(" x ") == "x"
    assert normalize("Fee: $1,975,000") == "fee: $1,975,000"  # content kept


def test_structural_key_composition():
    key = structural_key(["6.0 Accelerators", "6.0.2 Data Migration"], 3)
    assert key == "6.0 Accelerators/6.0.2 Data Migration#3"
    assert structural_key([], 0) == "#0"


def test_identity_block_fields():
    block = identity_block(TEXT, ["1. Approach"], 2, "f" * 64)
    assert block == {
        "content_hash": content_hash(TEXT),
        "structural_key": "1. Approach#2",
        "source_hash": "f" * 64,
    }
    # matched_from and drift are reconciliation outputs (C9), not mint-time
    assert "matched_from" not in block and "drift" not in block
