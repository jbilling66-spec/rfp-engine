"""CLI: engine intake run with an offline wire file produces a valid brief."""

import json

from engine.cli.main import main
from engine.contracts import validate
from tests.intake.fixtures.packages import FIXTURES


def test_intake_run_cli_offline_wire(tmp_path, capsys, monkeypatch):
    # The offline suite has no backend to resolve (docling absent; docker
    # state must not matter to make check) — the CLI runs under the
    # recorded override, which stamps the pdf degraded (asserted below).
    monkeypatch.setenv("RFP_EXTRACTION_FALLBACK", "1")
    wire = {
        "buyer": {"name": "Northwind Regional Health", "vertical": "healthcare"},
        "procurement": {
            "what_is_bought": "ERP implementation services",
            "response_structure": "free_flow",
            "deadlines": [{"label": "Proposal due", "date_text": "August 29, 2026"}],
        },
        "requirements": [
            {"ref": "3.1", "requirement": "Vendor shall provide an implementation plan.",
             "mandatory": True, "weight_text": "40%"},
        ],
        "red_flags": [],
    }
    wire_path = tmp_path / "wire.json"
    wire_path.write_text(json.dumps(wire), encoding="utf-8")

    rc = main([
        "intake", "run",
        "--outputs", str(tmp_path / "out"),
        "--pursuit", "pur_cli",
        "--doc", f"{FIXTURES / 'pdf-twin.pdf'}:rfp_main",
        "--ramble", "Fast turnaround, existing relationship.",
        "--wire", str(wire_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "brief:" in out

    brief = json.loads((tmp_path / "out" / "pur_cli" / "brief.json").read_text())
    validate("bid_brief", brief)
    assert brief["buyer"]["name"] == "Northwind Regional Health"
    assert brief["intake"]["ramble_context"] == "Fast turnaround, existing relationship."
    assert brief["requirements_matrix"][0]["weight"] == 40
    assert brief["requirements_matrix"][0]["weight_basis"] == "percent"

    # The override is honest: the checkpoint says legacy + degraded.
    ckpt = json.loads(
        (tmp_path / "out" / "pur_cli" / "checkpoints" / "intake.json").read_text()
    )["payload"]["docs"][0]
    assert ckpt["extractor"] == "pypdf"
    assert ckpt["extraction_degraded"] is True


def test_intake_run_cli_refuses_without_backend_or_override(tmp_path, capsys,
                                                            monkeypatch):
    # The owner's call (B58): no backend and no explicit override -> the run
    # REFUSES with instructions, never a silent downgrade. Probes are
    # patched so the verdict cannot depend on this machine's docker state.
    import engine.extraction.backend as backend_mod

    monkeypatch.delenv("RFP_EXTRACTION_FALLBACK", raising=False)
    monkeypatch.setattr(backend_mod, "_docling_importable", lambda: False)
    monkeypatch.setattr(backend_mod, "_docker_ready", lambda image: False)
    (tmp_path / "unused-wire.json").write_text("{}", encoding="utf-8")
    rc = main([
        "intake", "run",
        "--outputs", str(tmp_path / "out"),
        "--pursuit", "pur_cli",
        "--doc", f"{FIXTURES / 'pdf-twin.pdf'}:rfp_main",
        "--wire", str(tmp_path / "unused-wire.json"),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    assert "status: refused" in out
    assert "make gate-image" in out
    # No brief was produced — refusal happened before any model call.
    assert not (tmp_path / "out" / "pur_cli" / "brief.json").exists()


def test_intake_run_cli_rejects_malformed_doc_spec(tmp_path):
    rc = main([
        "intake", "run",
        "--outputs", str(tmp_path / "out"),
        "--pursuit", "pur_cli",
        "--doc", "no-kind-here",
        "--wire", str(tmp_path / "missing.json"),
    ])
    assert rc == 1
