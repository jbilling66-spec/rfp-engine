"""P29a (P1-49): the buyer's identifier index, in the workspace layer so
every door that persists human text about a pursuit builds the SAME
index — the accept-time learn route, Gate 0's opt-in gap→card and the
ping lane's opt-in (moved from engine/web/learn.py: the kb layer must
not import the web layer, and the workspace layer already imports kb,
so the door passes the DICT down to the spawner)."""

from pathlib import Path


def read_brief(pursuit) -> dict:
    """The frozen bid brief when there is one, else the live brief.json,
    else nothing — the index is never a guess."""
    from engine.contracts import ContractError
    try:
        return pursuit.read_frozen("bid_brief")
    except (FileNotFoundError, ContractError):
        pass
    try:
        return pursuit.read_artifact("brief.json")
    except FileNotFoundError:
        return {}


def buyer_identifiers(workspace: Path, pursuit, *,
                      brief: dict | None = None) -> dict[str, str]:
    """The buyer's names → CLIENT: the brief's buyer.name and, when the
    pursuit is linked to an organization, every alias the registry
    knows (P17/C6). `brief` lets Gate 0 pass the brief it is mutating
    (the org link stamps in memory before the write). Empty when nothing
    is known — then nothing is replaced, and the structured classes and
    the harness (M-27) are the backstop."""
    from engine.contracts import ContractError
    from engine.workspace.orgs import read_org

    buyer = ((brief if brief is not None else read_brief(pursuit))
             .get("buyer") or {})
    names = [buyer.get("name") or ""]
    if buyer.get("org_id"):
        try:
            names.extend(read_org(workspace, buyer["org_id"]).get("known_as") or [])
        except ContractError:
            pass
    return {name.strip(): "CLIENT" for name in names if name and name.strip()}
