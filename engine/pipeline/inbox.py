"""The inbox as the pipeline's input (P32c, A3's zero-spend half): the
ONE place a pursuit's declared-target set and its intake package are
read off `inbox/`. The web advance job read them inline since P16/C5
("THE one declared-target resolver"); the replay runner needs the same
rule, so the rule moved here and both doors call it — a declared DOCX
target can never fall to glob order in one door while another honors
it. Messages are the web door's, verbatim: operators learned them."""

import json
from pathlib import Path

from engine.contracts import ContractError
from engine.intake.brief import IntakeDoc, IntakePackage

READABLE = (".pdf", ".docx", ".xlsx")


def read_roles(root: Path) -> dict:
    """inbox/roles.json as written by the upload door — {} when the
    inbox is undeclared (the legacy first-workbook shape)."""
    roles_path = Path(root) / "inbox" / "roles.json"
    return (json.loads(roles_path.read_text(encoding="utf-8"))
            if roles_path.exists() else {})


def resolve_targets(root: Path) -> dict:
    """THE one declared-target resolver (P16/C5): every consumer of
    "which file(s) is the response vehicle" — the advance job, the
    gate-collapse job, the cost forecast, the replay runner — goes
    through here. Declared roles are authoritative (targets in filename
    order, ANY parseable type — parse_target owns the loud refusal for
    unsupported ones); a missing declared file refuses; an undeclared
    inbox keeps the legacy first-workbook behavior byte-for-byte."""
    inbox = Path(root) / "inbox"
    roles = read_roles(root)
    if roles:
        targets = [inbox / n for n in sorted(roles)
                   if roles[n] == "target"]
        missing = [t.name for t in targets if not t.is_file()]
        if missing:
            raise ContractError(
                "declared target(s) missing from inbox/: "
                + ", ".join(missing))
        core = next((inbox / n for n in sorted(roles)
                     if roles[n] == "core"), None)
        return {"targets": targets, "core": core, "declared": True}
    workbooks = sorted(inbox.glob("*.xlsx"))
    return {"targets": workbooks[:1], "core": None, "declared": False}


def package_from_inbox(pursuit_id: str, root: Path) -> IntakePackage:
    """The intake package the web advance job builds from `inbox/`: a
    declared inbox names its documents by role (one must be `core`), an
    undeclared one reads the first workbook; `ramble.md` rides along
    when present. Refuses typed when there is nothing to read."""
    inbox = Path(root) / "inbox"
    roles = read_roles(root)
    ramble = inbox / "ramble.md"
    ramble_text = ramble.read_text(encoding="utf-8") if ramble.exists() else ""
    if roles:
        docs = []
        for path in sorted(inbox.iterdir()):
            if path.suffix.lower() not in READABLE:
                continue
            role = roles.get(path.name)
            docs.append(IntakeDoc(
                path=path,
                kind=("rfp_main" if role == "core" else "other"),
                role=role))
        if not docs:
            raise ContractError(
                "roles.json names no readable documents — "
                "upload the RFP package first")
        if not any(d.role == "core" for d in docs):
            raise ContractError(
                "no document declared role=core — the one you "
                "would read if you read only one (B67 §3)")
        return IntakePackage(pursuit_id=pursuit_id, docs=docs,
                             ramble=ramble_text)
    workbooks = sorted(inbox.glob("*.xlsx"))
    if not workbooks:
        raise ContractError(
            "no .xlsx in inbox/ — upload the RFP package first")
    return IntakePackage(
        pursuit_id=pursuit_id,
        docs=[IntakeDoc(path=workbooks[0], kind="rfp_main")],
        ramble=ramble_text)
