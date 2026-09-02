"""The telemetry surface (c21).

Derive-never-store: figures are computed from the records at request
time, so a number on the screen cannot disagree with the record it
summarises. The screen and the release gate resolve through the SAME
metric objects — v1's eval numbers never reached its UI, and a dashboard
computing its own version of a gated number is exactly how the two
drift.
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from engine.web.server import create_app
from tests.web.conftest import FIXED_AT, raising_caller, sign_in

FIXTURE_WS = None


@pytest.fixture
def client(tmp_path):
    """A workspace carrying the committed fixture pursuit, so the view
    has real records to resolve over rather than an empty set."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "fixtures" / "pursuits"
              / "pur_metrics")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shutil.copytree(source, workspace / "pur_metrics")
    app = create_app(workspace, make_caller=raising_caller,
                     now=lambda: FIXED_AT)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sign_in(client, "Sam Owner")
        yield client


def test_the_system_owner_view_renders_every_declared_metric(client):
    from engine.metrics.views import VIEWS

    payload = client.get("/api/telemetry").json()
    assert payload["view"] == "system_owner_weekly"
    ids = [m["metric_id"] for m in payload["metrics"]]
    assert ids == VIEWS["system_owner_weekly"], (
        "the view renders what it declares, in order")


def test_absent_metrics_say_why_rather_than_vanishing(client):
    """A screen that silently drops what it cannot compute teaches its
    reader that everything shown is everything there is."""
    payload = client.get("/api/telemetry").json()
    absent = [m for m in payload["metrics"] if m["status"] == "absent"]
    assert absent, "the fixture cannot source every metric"
    for row in absent:
        assert row["absent_reason"]
        assert row["value"] is None


def test_small_samples_render_as_counts_not_rates(client):
    payload = client.get("/api/telemetry").json()
    counted = [m for m in payload["metrics"] if m["status"] == "count_only"]
    assert counted, "the fixture is deliberately small"
    for row in counted:
        assert "n=" in row["display"]


def test_the_bench_view_is_separate_and_says_so(client):
    payload = client.get("/api/telemetry/bench").json()
    assert payload["view"] == "bench"
    production = client.get("/api/telemetry").json()
    assert set(m["metric_id"] for m in payload["metrics"]).isdisjoint(
        m["metric_id"] for m in production["metrics"])


def test_the_bench_view_reads_the_record_and_never_runs_the_suite(
        client, tmp_path, monkeypatch):
    """A dashboard that could trigger a long eval run is a dashboard that
    can hang. With no record written, it says so.

    The releases dir is redirected at an empty tmp path rather than
    trusting the real one to be empty: `make eval` writes a record on
    every run by design (B40/D4), so a test asserting absence against the
    live directory passes only until someone runs the other make target.
    It did exactly that, and `make eval` then broke `make check` for the
    next person — the two documented commands must not be hostile to each
    other."""
    from engine.evals import release as release_mod

    monkeypatch.setattr(release_mod, "RELEASES_DIR", tmp_path / "empty")
    payload = client.get("/api/telemetry/bench").json()
    assert payload["release"] is None
    assert "make eval" in payload["release_absent_reason"]


def test_make_eval_output_does_not_break_make_check(client, tmp_path,
                                                    monkeypatch):
    """The regression that motivates the redirect above: a record sitting
    in the releases dir must change what the bench view SHOWS without
    changing whether the suite passes."""
    from engine.evals import release as release_mod
    from engine.version import engine_version

    releases = tmp_path / "releases"
    (releases / engine_version()).mkdir(parents=True)
    (releases / engine_version() / "eval-results.json").write_text(
        json.dumps({
            "engine_version": engine_version(), "generated_at": FIXED_AT,
            "eval_pass_state": False, "blocking_failures": ["poison.recall"],
            "suites": {}, "gates": [],
        }), encoding="utf-8")
    monkeypatch.setattr(release_mod, "RELEASES_DIR", releases)

    present = client.get("/api/telemetry/bench")
    assert present.status_code == 200
    assert present.json()["release"] is not None

    monkeypatch.setattr(release_mod, "RELEASES_DIR", tmp_path / "gone")
    absent = client.get("/api/telemetry/bench")
    assert absent.status_code == 200
    assert absent.json()["release"] is None


def test_the_bench_view_surfaces_a_written_record(client, tmp_path,
                                                  monkeypatch):
    from engine.evals import release as release_mod

    version = __import__("engine.version", fromlist=["engine_version"]) \
        .engine_version()
    releases = tmp_path / "releases"
    (releases / version).mkdir(parents=True)
    (releases / version / "eval-results.json").write_text(json.dumps({
        "engine_version": version, "generated_at": FIXED_AT,
        "eval_pass_state": False,
        "blocking_failures": ["poison.recall"],
        "suites": {"poison": {"status": "fail", "basis": "live_baseline"}},
        "gates": [{"clause": 1, "status": "fail"}],
    }), encoding="utf-8")
    monkeypatch.setattr(release_mod, "RELEASES_DIR", releases)

    payload = client.get("/api/telemetry/bench").json()
    assert payload["release"]["eval_pass_state"] is False
    assert payload["release"]["blocking_failures"] == ["poison.recall"]


def test_the_screen_and_the_resolver_agree(client):
    """The property v1 lacked: one metric object feeds both the view and
    the gate, so they cannot report different numbers."""
    from pathlib import Path

    from engine.metrics.resolver import Corpus, resolve

    payload = client.get("/api/telemetry").json()
    workspace = Path(client.app.state.workspace)
    corpus = Corpus(workspace)
    for row in payload["metrics"]:
        direct = resolve(row["metric_id"], corpus)
        assert row["value"] == direct["value"]
        assert row["status"] == direct["status"]


def test_telemetry_reads_are_open_but_change_nothing(client, tmp_path):
    """Reads are open on a localhost bind (D17). The important half is
    that a read writes nothing — no phantom pursuit, no stored figure."""
    workspace = tmp_path / "ws"
    before = sorted(p.name for p in workspace.iterdir())
    client.get("/api/telemetry")
    client.get("/api/telemetry/bench")
    assert sorted(p.name for p in workspace.iterdir()) == before
