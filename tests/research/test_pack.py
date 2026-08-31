"""Pack loader contract (B21(5)): the loader IS the contract, so its refusals
are tested as hard as its parse. Goldens are hand-transcribed in
fixtures/pursuits.py, never derived by the loader under test."""

import hashlib

import pytest

from engine.research import ResearchPackError, load_pack
from tests.research.fixtures.pursuits import PACK_PATH, PACK_SECTIONS, PACK_TITLE


def test_committed_fixture_parses_to_goldens():
    pack = load_pack(PACK_PATH)
    assert pack.title == PACK_TITLE
    assert [s.heading for s in pack.sections] == list(PACK_SECTIONS)
    for section in pack.sections:
        url, marker = PACK_SECTIONS[section.heading]
        assert section.source_url == url
        assert marker in section.body


def test_sha256_recomputes_from_file_bytes():
    pack = load_pack(PACK_PATH)
    assert pack.sha256 == hashlib.sha256(PACK_PATH.read_bytes()).hexdigest()


def _write(tmp_path, text):
    path = tmp_path / "pack.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_title_raises(tmp_path):
    path = _write(tmp_path, "## Section\nsource: https://example.org/x\nBody.\n")
    with pytest.raises(ResearchPackError, match="first line must start"):
        load_pack(path)


def test_zero_sections_raises(tmp_path):
    path = _write(tmp_path, "# Research pack: something\n\nProse only.\n")
    with pytest.raises(ResearchPackError, match="no '## ' sections"):
        load_pack(path)


def test_missing_source_line_raises(tmp_path):
    path = _write(tmp_path,
                  "# Research pack: something\n\n## Topic\nBody without source.\n")
    with pytest.raises(ResearchPackError, match="first line must be 'source:"):
        load_pack(path)


def test_non_http_scheme_raises(tmp_path):
    path = _write(tmp_path,
                  "# Research pack: something\n\n## Topic\nsource: ftp://x.org/f\nBody.\n")
    with pytest.raises(ResearchPackError, match="first line must be 'source:"):
        load_pack(path)


def test_empty_section_body_raises(tmp_path):
    path = _write(tmp_path,
                  "# Research pack: something\n\n## Topic\nsource: https://example.org/x\n")
    with pytest.raises(ResearchPackError, match="has no body text"):
        load_pack(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ResearchPackError, match="not found"):
        load_pack(tmp_path / "absent.md")
