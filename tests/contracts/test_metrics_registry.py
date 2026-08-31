"""The live metric registry (config/metrics.json) stays valid and honest (B11).

Every entry validates against metric-definition.schema.json; formula strings
that reference schema enums use values those enums actually contain (the
'complete' vs 'completed' erratum, generalized); and the registry keeps
exactly one definition per metric_id.
"""

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / "config" / "metrics.json").read_text(encoding="utf-8"))
SCHEMA = json.loads(
    (ROOT / "schemas" / "metric-definition.schema.json").read_text(encoding="utf-8")
)
_RUN_LOG = json.loads(
    (ROOT / "schemas" / "run-log.schema.json").read_text(encoding="utf-8")
)
RUN_STATUS_ENUM = set(_RUN_LOG["properties"]["run"]["properties"]["status"]["enum"])
VALIDATION_CHECK_ENUM = set(
    _RUN_LOG["properties"]["validation"]["properties"]["check"]["enum"]
)
RUN_MODE_ENUM = set(_RUN_LOG["properties"]["run"]["properties"]["mode"]["enum"])
FEEDBACK_KIND_ENUM = set(
    json.loads(
        (ROOT / "schemas" / "feedback-event.schema.json").read_text(encoding="utf-8")
    )["properties"]["kind"]["enum"]
)


def test_registry_has_35_unique_metric_ids():
    ids = [m["metric_id"] for m in REGISTRY]
    assert len(ids) == 35  # 30 -> 35 at P13/C18 (B51's §A6 metrics)
    assert len(set(ids)) == 35


@pytest.mark.parametrize("metric", REGISTRY, ids=lambda m: m["metric_id"])
def test_metric_validates_against_schema(metric):
    Draft202012Validator(SCHEMA).validate(metric)


def test_run_status_references_use_real_enum_values():
    for metric in REGISTRY:
        formula = metric.get("formula", "")
        for value in re.findall(r"run\.status == '([a-z_]+)'", formula):
            assert value in RUN_STATUS_ENUM, (
                f"{metric['metric_id']} formula references run.status "
                f"'{value}' which is not in the schema enum"
            )


# filter-string pattern -> the schema enum its quoted values must belong to
# (the B13 erratum, generalized: anonymization_scan_result filtered on
# validation.check values the enum did not contain)
_FILTER_ENUM_PATTERNS = [
    (r"(?:validation\.)?check (?:==|in) (.+)", "validation.check"),
    (r"run\.mode (?:==|in) (.+)", "run.mode"),
    (r"^kind (?:==|in) (.+)", "feedback-event.kind"),
]


def test_every_cost_bearing_metric_excludes_synthetic_spend():
    """FakeCaller logs non-zero synthetic cost_usd on every dry_run (the cost
    meter must exercise offline). A cost-bearing metric without the live-mode
    filter would absorb those fabricated dollars into a finance-facing figure —
    the filter is required, not conventional (B30; caught cost_per_win live)."""
    for metric in REGISTRY:
        source = metric.get("source", {})
        cost_bearing = (
            metric.get("unit") == "usd"
            or "cost_usd" in metric.get("formula", "")
            or any("cost_usd" in f for f in source.get("fields", []))
        )
        if not cost_bearing:
            continue
        assert "run.mode == 'live'" in source.get("filters", []), (
            f"{metric['metric_id']} is cost-bearing but does not exclude "
            f"synthetic (dry_run/replay) spend via run.mode == 'live'"
        )


def test_filter_references_use_real_enum_values():
    enums = {
        "validation.check": VALIDATION_CHECK_ENUM,
        "run.mode": RUN_MODE_ENUM,
        "feedback-event.kind": FEEDBACK_KIND_ENUM,
    }
    for metric in REGISTRY:
        for filt in metric.get("source", {}).get("filters", []):
            for pattern, enum_name in _FILTER_ENUM_PATTERNS:
                match = re.search(pattern, filt)
                if not match:
                    continue
                for value in re.findall(r"'([a-z_]+)'", match.group(1)):
                    assert value in enums[enum_name], (
                        f"{metric['metric_id']} filter {filt!r} references "
                        f"{enum_name} '{value}' which is not in the schema enum"
                    )
