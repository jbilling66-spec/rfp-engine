"""B17: red flags are typed objects and weights carry a basis.

The three flag kinds the spec makes first-class (injection — S2/T1,
ai_use — C2, independence_oci — C3) must be machine-distinguishable;
a bare-string red flag can no longer validate.
"""

import pytest

from engine.contracts import ContractError, validate

_BRIEF = {
    "pursuit_id": "pur_t",
    "buyer": {"name": "Synthetic Northwind Health"},
    "procurement": {},
    "requirements_matrix": [],
    "status": "draft",
}


def _with(procurement=None, matrix=None):
    brief = dict(_BRIEF)
    if procurement is not None:
        brief["procurement"] = procurement
    if matrix is not None:
        brief["requirements_matrix"] = matrix
    return brief


def test_typed_red_flag_validates():
    flags = [
        {
            "kind": "ai_use",
            "detail": "Solicitation requires disclosure of AI use in preparation.",
            "excerpt": "Vendors must disclose any use of generative AI.",
            "source_location": "rfp.pdf p2",
            "detected_by": "model",
        },
        {
            "kind": "independence_oci",
            "detail": "OCI certification clause.",
            "routed_to": "conflicts_process",
        },
    ]
    validate("bid_brief", _with(procurement={"red_flags": flags}))


def test_bare_string_red_flag_rejected():
    with pytest.raises(ContractError):
        validate("bid_brief", _with(procurement={"red_flags": ["wired for incumbent"]}))


def test_unknown_flag_kind_rejected():
    flag = {"kind": "vibes", "detail": "not a vocabulary value"}
    with pytest.raises(ContractError):
        validate("bid_brief", _with(procurement={"red_flags": [flag]}))


def test_flag_requires_kind_and_detail():
    with pytest.raises(ContractError):
        validate("bid_brief", _with(procurement={"red_flags": [{"kind": "injection"}]}))


def test_weight_with_basis_validates():
    row = {"ref": "2.0.1", "requirement": "Describe integration approach.", "weight": 30, "weight_basis": "percent"}
    validate("bid_brief", _with(matrix=[row]))


def test_invalid_weight_basis_rejected():
    row = {"requirement": "r", "weight": 30, "weight_basis": "fraction"}
    with pytest.raises(ContractError):
        validate("bid_brief", _with(matrix=[row]))
