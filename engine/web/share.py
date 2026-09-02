"""Share links (B37/D16, the owner's Q1 override): read-only view + guest
COMMENTS, expiring, pursuit-scoped. Guests do exactly two things.

Token discipline (D16a): `links.jsonl` keeps the SECRET token; every
record a guest's activity produces carries only the PUBLIC `link_id`
(sl_NN) — the secret appears in no event, no round record, no access
line, so nothing exportable ever leaks it. Guest identity is a
self-declared display name bound to the link; the `share:` actor prefix
IS the structural unverified marker until A5 brings real external
identity. Revoke is an appended line (last-wins) — the P9 kill switch.

`access.jsonl` logs every guest READ and WRITE attempt, denials
included, stamped with the request's injected `at` (deterministic in
tests, real upstream). Its line shape is its own — the KB restricted
store's access-log schema keeps its closed purpose vocabulary (S8: a
purpose any caller can invent is a comment, not a control), and
widening it for share actions would dilute exactly that. Recorded as a
decide-and-log deviation from D23's "shared schema" sketch.
"""

import json
import os
import secrets
import threading
from datetime import datetime, timedelta


_MINT_LOCK = threading.Lock()  # P1-22: link ids mint under a process lock


MAX_LINK_DAYS = 30  # P25 item 4 (P3-12): no century-long guest links


class ShareDenied(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _parse(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def default_token_factory() -> str:
    return secrets.token_urlsafe(24)


class ShareLane:
    def __init__(self, pursuit):
        self.pursuit = pursuit
        self.links_path = pursuit.root / "share" / "links.jsonl"
        self.access_path = pursuit.root / "share" / "access.jsonl"

    def _append(self, path, line: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _folded(self) -> dict[str, dict]:
        if not self.links_path.exists():
            return {}
        out: dict[str, dict] = {}
        for raw in self.links_path.read_text(encoding="utf-8").splitlines():
            line = json.loads(raw)
            out[line["link_id"]] = {**out.get(line["link_id"], {}), **line}
        return out

    def log_access(self, *, at: str, link_id: str | None, action: str,
                   granted: bool, detail: str = "") -> None:
        line = {"at": at, "link_id": link_id, "action": action,
                "granted": granted}
        if detail:
            line["detail"] = detail
        self._append(self.access_path, line)

    # -- lifecycle ---------------------------------------------------------

    def create(self, *, created_by: str, label: str, expires_at: str,
               at: str, token_factory=default_token_factory) -> dict:
        if not label.strip():
            raise ShareDenied(422, "a label is required — the link record "
                                   "is who this link is FOR")
        try:
            if _parse(expires_at) <= _parse(at):
                raise ShareDenied(422, "expires_at must be in the future")
            if _parse(expires_at) > _parse(at) + timedelta(days=MAX_LINK_DAYS):
                raise ShareDenied(422, f"expires_at may be at most "
                                       f"{MAX_LINK_DAYS} days out (P3-12)")
        except ValueError:
            raise ShareDenied(422, f"expires_at must be ISO 8601, got "
                                   f"{expires_at!r}")
        with _MINT_LOCK:  # P1-22: max(existing)+1, minted and appended together
            seen = [int(k[3:]) for k in self._folded() if k[3:].isdigit()]
            record = {"link_id": f"sl_{(max(seen) + 1) if seen else 1:02d}",
                      "token": token_factory(),
                      "pursuit_id": self.pursuit.pursuit_id,
                      "created_by": created_by, "label": label,
                      "created_at": at, "expires_at": expires_at}
            self._append(self.links_path, record)
        return record

    def revoke(self, *, link_id: str, by: str, at: str) -> dict:
        record = self._folded().get(link_id)
        if record is None:
            raise ShareDenied(404, f"unknown link {link_id!r}")
        self._append(self.links_path,
                     {"link_id": link_id, "revoked": True,
                      "revoked_by": by, "revoked_at": at})
        return {**record, "revoked": True}

    def links(self) -> list[dict]:
        return sorted(self._folded().values(),
                      key=lambda r: r["link_id"])

    # -- resolution (every attempt logged, granted or not) -----------------

    def resolve(self, token: str, *, at: str, action: str) -> dict:
        record = next((r for r in self._folded().values()
                       if secrets.compare_digest(str(r.get("token", "")),
                                                 str(token))), None)
        if record is None:
            self.log_access(at=at, link_id=None, action=action,
                            granted=False, detail="unknown token")
            raise ShareDenied(404, "unknown share link")
        if record.get("revoked"):
            self.log_access(at=at, link_id=record["link_id"], action=action,
                            granted=False, detail="revoked")
            raise ShareDenied(410, "this share link was revoked")
        if _parse(at) >= _parse(record["expires_at"]):
            self.log_access(at=at, link_id=record["link_id"], action=action,
                            granted=False, detail="expired")
            raise ShareDenied(410, "this share link has expired")
        self.log_access(at=at, link_id=record["link_id"], action=action,
                        granted=True)
        return record
