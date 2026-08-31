"""Acceptance: ramble context influences the brief — and travels in the
firm-labeled frame, never the S1 untrusted frame."""

import re

from tests.intake.fixtures.packages import RAMBLE, _wire_from_prompt, run_package


def test_ramble_influences_brief(tmp_path):
    with_ramble, _ = run_package(tmp_path / "with", "pdf", ramble=RAMBLE)
    without_ramble, _ = run_package(tmp_path / "without", "pdf")
    brief = with_ramble.read_artifact("brief.json")
    bare = without_ramble.read_artifact("brief.json")

    assert brief["buyer"]["incumbent"] == "Summit Apex Consulting"
    assert "no onsite staffing before March" in brief["buyer"]["profile"]
    assert brief["intake"]["ramble_context"] == RAMBLE  # verbatim, code-copied

    assert "incumbent" not in bare["buyer"]
    assert "no onsite staffing" not in bare["buyer"].get("profile", "")
    assert "ramble_context" not in bare["intake"]


def test_ramble_is_lead_context_framed_and_docs_are_s1_framed(tmp_path):
    captured = {}

    def capturing(prompt: str) -> str:
        captured["prompt"] = prompt
        return _wire_from_prompt(prompt)

    run_package(tmp_path, "pdf", ramble=RAMBLE, script={"intake_analyst": capturing})
    prompt = captured["prompt"]

    lead = re.search(
        r'<pursuit_lead_context label="firm">\n(.*?)\n</pursuit_lead_context>',
        prompt, re.S,
    )
    assert lead is not None and RAMBLE in lead.group(1)

    sources = re.findall(r'<buyer_document source="([^"]+)" label="untrusted">', prompt)
    assert sources == ["pdf-twin.pdf"]  # every buyer doc S1-framed, exactly once

    for block in re.finditer(r"<buyer_document.*?</buyer_document>", prompt, re.S):
        assert RAMBLE not in block.group(0)  # ramble never rides inside S1
