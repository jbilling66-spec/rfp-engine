"""The contract-owned slot helpers (engine/contracts/slots.py): the join
key and the one shared definition of "takes no response"."""

from engine.contracts.slots import field_key, is_organizational, unique_keys


def test_field_key_is_a_stable_slug():
    assert field_key("Hourly rate") == "hourly_rate"
    assert field_key("Application/Vendor/Tools/Functional Area") == (
        "application_vendor_tools_funct"
    )  # the v1 fixture's exact 30-char truncation
    assert len(field_key("x" * 100)) == 30
    assert field_key("!!!") == "field"


def test_unique_keys_suffix_deterministically():
    # The v1 near-miss: two labels truncating to the same 30-char key.
    labels = ["Application Vendor Tools Functional Area",
              "Application Vendor Tools Functionality"]
    keys = unique_keys(labels)
    assert keys[0] != keys[1]
    assert keys == unique_keys(labels)  # deterministic


def test_is_organizational_matches_headers_and_shape_none():
    assert is_organizational({"is_header": True, "response_shape": "prose"})
    assert is_organizational({"response_shape": "none"})
    assert not is_organizational({"response_shape": "prose"})
