"""The revision fixture chain: extends the P8 validation harness (runs
0001-0006) with revise rounds (run 0007+). The revision_agent arm is the
PRODUCT-SIDE derive-from-prompt (engine/web/fake_script.py) — its
regexes pin the composer formats, the house discipline."""

from engine.kb import KBStore
from engine.llm import FakeCaller, TracedCaller, effective_config
from engine.revision import run_round
from engine.runlog import RunLogger
from engine.version import engine_version
from engine.web.events import EventsLane
from engine.web.fake_script import derive_revision_wire
from tests.validation.fixtures.validations import (
    AT,
    make_validation_script,
    run_validation_package,
    validation_extras,
)

ROUND_AT = "2026-08-10T09:00:00"
ACTOR = "Robin Reviewer"
ROLE = "pursuit_lead"


def round_script(**plants):
    script = make_validation_script(**plants)
    script["revision_agent"] = derive_revision_wire
    return script


def open_round_run(tmp_root, pursuit, *, script=None, fake=None):
    store = KBStore(tmp_root / "kb")
    log = RunLogger(pursuit.root, pursuit.new_run_id(), pursuit.pursuit_id)
    caller = TracedCaller(fake or FakeCaller(script or round_script()), log)
    cfg = effective_config(extra=validation_extras(store))
    log.run_start(mode="dry_run", engine_version=engine_version(),
                  config=cfg, kb_snapshot=store.snapshot(),
                  research_mode=cfg["research_mode"])
    return store, log, caller


def add_comment(pursuit, section_id, text, *, at=ROUND_AT, slot_id=None):
    return EventsLane(pursuit).add_pending(
        kind="comment", section_id=section_id, actor=ACTOR,
        actor_role=ROLE, at=at, slot_id=slot_id, text=text)


def run_one_round(tmp_root, pursuit, *, at=ROUND_AT, script=None, fake=None):
    store, log, caller = open_round_run(tmp_root, pursuit,
                                        script=script, fake=fake)
    report = run_round(pursuit, caller, log, store, at=at, actor=ACTOR)
    log.run_end(status="completed")
    return report, log


def validated_pursuit(tmp_root, **kwargs):
    pursuit, report, _ = run_validation_package(tmp_root, **kwargs)
    assert report.status == "complete"
    return pursuit
