"""engine_version() feeds every run-log header — retired vocabulary must not
regress into the permanent record (B29 retired "POC"; B30 caught the survivor)."""

from engine.version import VERSION, engine_version


def test_version_carries_no_retired_vocabulary():
    for value in (VERSION, engine_version()):
        assert "poc" not in value.lower(), (
            f"retired vocabulary in the version string: {value!r} (B29/B30)"
        )


def test_version_shape():
    assert VERSION == "0.1.0"
    assert engine_version().startswith(VERSION)
