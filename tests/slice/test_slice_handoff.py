"""The M1 slice through the handoff seam (P20/B81): the acceptance walk.
The suite plays the work-side answerer — a daemon thread that polls
pending-calls/ and answers each request by running the matching
ci_script() arm on the request's OWN prompt (derive-from-prompt, no
goldens), writing the response atomically. That keeps the byte-identity
law: a handoff walk and a FakeCaller walk produce the same artifacts,
because the judgment text has the same one source."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from engine.cli.main import build_parser, main
from engine.cli.slice import run_slice
from engine.cli.slice_script import ci_script
from engine.llm import HandoffTimeout
from engine.runlog import read_run
from engine.workspace import PursuitDir

ARTIFACTS = ("brief.json", "brief.frozen.json", "plan.json",
             "plan.frozen.json", "drafts/draft.json",
             "drafts/annotated-draft.json")


class _Operator(threading.Thread):
    """The work-side answerer, played by the suite. Answers every
    unanswered request with the ci_script() arm for its agent; writes
    tmp + os.replace (the atomicity P21's operator kit will instruct)."""

    def __init__(self, pending: Path):
        super().__init__(daemon=True)
        self.pending = Path(pending)
        self.stop_flag = threading.Event()
        self.script = ci_script()

    def run(self) -> None:
        while not self.stop_flag.is_set():
            if self.pending.is_dir():
                for request_path in sorted(
                        self.pending.glob("call-*.request.json")):
                    response_path = self.pending / request_path.name.replace(
                        ".request.", ".response.")
                    if response_path.exists():
                        continue
                    request = json.loads(
                        request_path.read_text(encoding="utf-8"))
                    entry = self.script.get(
                        request["agent"], f"[fake:{request['agent']}] ok")
                    text = (entry(request["prompt"]) if callable(entry)
                            else entry)
                    tmp = self.pending / ("." + response_path.name + ".tmp")
                    tmp.write_text(json.dumps(
                        {"seq": request["seq"], "agent": request["agent"],
                         "model": "test-operator", "text": text}),
                        encoding="utf-8")
                    os.replace(tmp, response_path)
            time.sleep(0.05)


def _with_operator(workspace: Path, fn):
    operator = _Operator(Path(workspace) / "pending-calls")
    operator.start()
    try:
        return fn()
    finally:
        operator.stop_flag.set()
        operator.join(timeout=5)


def _pursuit(workspace):
    return PursuitDir(workspace, "pur_demo")


@pytest.fixture(scope="module")
def handoff_happy(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("slice-handoff")
    result = _with_operator(
        workspace,
        lambda: run_slice(workspace, handoff=True, handoff_timeout=60,
                          out=lambda *_: None))
    return workspace, result


def test_handoff_slice_end_to_end(handoff_happy):
    workspace, result = handoff_happy
    assert result.status == "ok" and result.problems == []
    assert result.ran_stages == ["intake", "gate_0", "research",
                                 "win_themes+gate_1", "planning+gate_2",
                                 "drafting", "validation"]
    root = _pursuit(workspace).root
    for name in ARTIFACTS:
        assert (root / name).exists(), f"missing {name}"


def test_every_exchange_is_a_file_pair_and_an_agent_call_line(handoff_happy):
    """The acceptance clause verbatim: every judgment step answered
    through the seam leaves an auditable pair on disk AND an agent_call
    line — same count, handoff/-prefixed model, zero marginal dollar."""
    workspace, result = handoff_happy
    agent_calls = []
    for run_file in sorted(
            (_pursuit(workspace).root / "runs").glob("*/run.jsonl")):
        records = read_run(run_file)
        assert records[0]["run"]["mode"] == "handoff"
        agent_calls.extend(r for r in records
                           if r["record_type"] == "agent_call")
    assert agent_calls, "a walk with no judgment steps proves nothing"
    for record in agent_calls:
        assert record["model"] == "handoff/test-operator"
        assert record["cost_usd"] == 0.0
    pending = workspace / "pending-calls"
    requests = list(pending.glob("call-*.request.json"))
    responses = list(pending.glob("call-*.response.json"))
    assert len(agent_calls) == len(requests) == len(responses)
    assert result.cost_usd == 0.0  # seat-consumed judgment, no dollars


def test_handoff_walk_matches_a_fakecaller_walk_byte_for_byte(
        handoff_happy, tmp_path):
    """The determinism law across transports: same judgment source (the
    ci_script arms), same artifacts — the transport leaves no residue."""
    workspace, _ = handoff_happy
    fake = run_slice(tmp_path, out=lambda *_: None)
    assert fake.status == "ok"
    for name in ARTIFACTS:
        assert (_pursuit(workspace).root / name).read_bytes() \
            == (_pursuit(tmp_path).root / name).read_bytes(), name


def test_absent_operator_times_out_then_resume_completes(
        handoff_happy, tmp_path):
    """The refusal half, then the recovery half: no operator -> a typed
    HandoffTimeout and the unanswered request remains on disk; a resumed
    walk with the operator present completes byte-identical."""
    with pytest.raises(HandoffTimeout, match="call-0001.request.json"):
        run_slice(tmp_path, handoff=True, handoff_timeout=1.5,
                  out=lambda *_: None)
    pending = tmp_path / "pending-calls"
    assert (pending / "call-0001.request.json").exists()
    assert not (pending / "call-0001.response.json").exists()
    root = _pursuit(tmp_path).root
    assert not (root / "drafts" / "annotated-draft.json").exists()

    resumed = _with_operator(
        tmp_path,
        lambda: run_slice(tmp_path, handoff=True, handoff_timeout=60,
                          out=lambda *_: None))
    assert resumed.status == "ok"
    workspace, _ = handoff_happy
    for name in ARTIFACTS:
        assert (root / name).read_bytes() \
            == (_pursuit(workspace).root / name).read_bytes(), name


def test_handoff_flag_registered_and_exclusive_with_live():
    parser = build_parser()
    args = parser.parse_args(["slice"])
    assert args.handoff is False and args.handoff_timeout == 900.0
    assert parser.parse_args(["slice", "--handoff"]).handoff is True
    with pytest.raises(SystemExit):
        parser.parse_args(["slice", "--live", "--handoff"])


def test_cli_entry_returns_zero_through_the_handoff_flag(tmp_path):
    workspace = tmp_path / "ws"
    code = _with_operator(
        workspace,
        lambda: main(["slice", "--handoff", "--fresh", "--workspace",
                      str(workspace), "--handoff-timeout", "60"]))
    assert code == 0
