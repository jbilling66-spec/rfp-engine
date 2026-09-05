"""M-20 (P26b-3): engine/contracts/paths.py::within — the containment
guard lifted from its inline copies. A caller-supplied name resolves
inside the root or refuses typed, naming the root."""

import pytest

from engine.contracts import ContractError, within


def test_a_name_inside_the_root_resolves(tmp_path):
    (tmp_path / "a").mkdir()
    assert within(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()


@pytest.mark.parametrize("name", ["../x", "a/../../x", "/etc/hosts"])
def test_an_escape_is_refused_naming_the_root(tmp_path, name):
    with pytest.raises(ContractError, match="escapes"):
        within(tmp_path, name)


def test_a_symlink_out_of_the_root_is_refused(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(ContractError, match="escapes"):
        within(tmp_path, "link/x")
