"""The replay bench (P32c — A3's zero-spend half): the deterministic
subject the `replay` eval lane measures and the acceptance tests drive.

The CI slice runs into a scratch workspace; the demo workbook and
ramble are deposited into the bench pursuit's inbox (the convention
every web pursuit already has, so the replay reads the production
path); a scratch copy of the seeded KB gains two SYNTHETIC cards — one
sourced from the bench pursuit, one derived from it — whose catalog
words copy the demo's first research topic, so that with the exclusion
OFF the first would rank first and be opened. Then the pursuit is
replayed against that KB and the verdict is read off the replay's
trace: the exclusion fired, nothing self-excluded was surfaced or
opened, the headers and gates say replay. A bench whose exclusion set
is empty or whose exclusion never fired is a vacuous measure (P2-36),
refused by name — never a pass over nothing.
"""

import shutil
import tempfile
from pathlib import Path

from engine.cli.replay import run_replay
from engine.cli.slice import DEMO_RAMBLE, DEMO_WORKBOOK, KB_ROOT, run_slice
from engine.evals.trajectory import check_assertion
from engine.kb import KBStore
from engine.runlog import read_run

BENCH_PURSUIT = "pur_demo"
PLANTED_ID = "kb_replaybench01"  # sourced from the bench pursuit
DERIVED_ID = "kb_replaybench02"  # derived from it, another source
PLANTED_CLIENT = "Replay Bench Health Collaborative"  # synthetic
# the demo's first research topic, word for word (derive_topics over the
# demo brief) — the planted card must be able to win it
BENCH_TOPIC = "regional health system strategic priorities"


def plant_self_sourced_cards(store: KBStore, pursuit_id: str) -> list[str]:
    """Two synthetic cards through the real write seam. Catalog text
    saturated with the bench topic so the planted card outranks the
    corpus for it when nothing withholds it."""
    store.write_card(
        {"kb_id": PLANTED_ID, "layer": "corpus",
         "title": "Regional health system strategic priorities",
         "summary": ("Strategic priorities of a regional health system: "
                     "the priorities a regional health system sets, and how "
                     "each strategic priority of the health system is funded."),
         "canonical_block": False, "use_restriction": False,
         "outcome": "won"},
        ("Synthetic replay-bench body: a regional health system's strategic "
         "priorities, written for the bench and never a firm text."),
        {"source_pursuit": pursuit_id, "source_client": PLANTED_CLIENT,
         "date": "2026-01-01", "ingested_by": "replay_bench"},
        {})
    store.write_card(
        {"kb_id": DERIVED_ID, "layer": "corpus",
         "title": "Note derived from the bench priorities card",
         "summary": "A synthetic note derived from the replay bench card.",
         "canonical_block": False, "use_restriction": False,
         "outcome": "won"},
        "Synthetic derived body for the replay bench.",
        {"source_pursuit": "pur_replay_bench_other",
         "source_client": PLANTED_CLIENT, "date": "2026-01-02",
         "ingested_by": "replay_bench", "derived_from": [PLANTED_ID]},
        {})
    return [PLANTED_ID, DERIVED_ID]


def deposit_inbox(workspace: Path, pursuit_id: str = BENCH_PURSUIT) -> Path:
    """The slice reads its demo package from tests/fixtures; a web
    pursuit carries its package in inbox/. Deposit the same files so the
    bench pursuit conforms to the inbox convention the replay reads."""
    inbox = Path(workspace) / pursuit_id / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEMO_WORKBOOK, inbox / DEMO_WORKBOOK.name)
    shutil.copy2(DEMO_RAMBLE, inbox / "ramble.md")
    return inbox


def replay_bench(workdir: Path | None = None, *,
                 out=lambda *_a, **_k: None) -> dict:
    """Run the bench; return its measures. With `workdir` the files
    stay for inspection; without it they live in a temporary directory
    and only the measures survive."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(workdir) if workdir else Path(tmp)
        workspace = base / "ws"
        sliced = run_slice(workspace, out=out)
        if sliced.status != "ok":
            return {"status": sliced.status,
                    "problems": ["the CI slice did not complete: "
                                 + "; ".join(sliced.problems)]}
        deposit_inbox(workspace)
        kb_root = base / "kb"
        shutil.copytree(KB_ROOT, kb_root)
        planted = plant_self_sourced_cards(KBStore(kb_root), BENCH_PURSUIT)
        replay = run_replay(workspace, BENCH_PURSUIT, kb_root=kb_root, out=out)
        report = {
            "status": replay.status,
            "problems": list(replay.problems),
            "planted": planted,
            "self_exclusion": list(replay.self_exclusion),
            "self_exclusion_size": len(replay.self_exclusion),
            "excluded_lines": replay.excluded_lines,
            "surfaced_excluded": list(replay.surfaced_excluded),
            "surfaced_excluded_count": len(replay.surfaced_excluded),
            "opened_excluded": list(replay.opened_excluded),
            "opened_excluded_count": len(replay.opened_excluded),
            "replay_runs": replay.runs,
            "headers_ok": replay.headers_ok,
            "gates_auto_approved": replay.gates_auto_approved,
            "workspace": str(workspace),
            "kb_root": str(kb_root),
            "replay_root": str(replay.replay_root) if replay.replay_root else None,
        }
        if replay.status == "ok":
            records = [r for run in sorted(
                           (replay.replay_root / "runs").glob("*/run.jsonl"))
                       for r in read_run(run)]
            holds, detail = check_assertion(
                records, {"assert": "no_excluded_card_opened"})
            report["no_excluded_card_opened"] = holds
            report["trajectory_detail"] = detail
        else:
            report["no_excluded_card_opened"] = False
            report["trajectory_detail"] = "the replay did not complete"
        return report
