"""Operator identity (B37/D17): declared | header, chosen once at app
construction from config/web.yaml.

Declared mode is the pre-A5 reality — the operator declares a name, a
token cookie carries it, and the name lands in exactly the fields the
headless contracts fill (gate actor, waived_by, event actor), so
decision artifacts do not change shape when the identity source swaps
to the A5 SSO proxy. Header mode is that seam: identity comes from a
reverse proxy that authenticates and SETS the header (stripping any
client-supplied copy); /api/session is disabled there.

Every MUTATING route requires an operator; reads are open (127.0.0.1
bind). Sessions are in-memory by design: lost on restart, which is the
honest lifetime of a declared identity. (v1 keeper design, reimplemented.)
"""

import secrets
from pathlib import Path

import yaml
from fastapi import HTTPException, Request

_CONFIG_DEFAULT = Path(__file__).resolve().parents[2] / "config" / "web.yaml"


class AuthSeam:
    def __init__(self, config_path: Path | None = None):
        cfg = yaml.safe_load(
            (config_path or _CONFIG_DEFAULT).read_text(encoding="utf-8"))
        auth = cfg.get("auth", {})
        self.mode = auth.get("mode", "declared")
        if self.mode not in ("declared", "header"):
            raise ValueError(f"web auth.mode must be declared|header, "
                             f"got {self.mode!r}")
        self.header_name = auth.get("header_name", "X-Auth-User")
        self._sessions: dict[str, str] = {}

    # -- declared mode ---------------------------------------------------

    def establish(self, name: str) -> str:
        if self.mode != "declared":
            raise HTTPException(
                400, "identity comes from the SSO proxy in header mode — "
                     "/api/session is disabled")
        name = " ".join(str(name).split())
        if not 2 <= len(name) <= 60:
            raise HTTPException(422, "operator name must be 2-60 characters")
        token = secrets.token_urlsafe(24)
        self._sessions[token] = name
        return token

    # -- the dependency ---------------------------------------------------

    def operator(self, request: Request) -> str:
        if self.mode == "header":
            name = " ".join(
                (request.headers.get(self.header_name) or "").split())
            if not name:
                raise HTTPException(
                    401, f"no {self.header_name} header — this deployment "
                         "expects an authenticating SSO reverse proxy to "
                         "set it")
            return name
        token = (request.cookies.get("operator")
                 or request.headers.get("x-operator-token"))
        name = self._sessions.get(token or "")
        if not name:
            raise HTTPException(
                401, "no operator session — declare who you are first "
                     "(POST /api/session)")
        return name

    def whoami(self, request: Request) -> str | None:
        try:
            return self.operator(request)
        except HTTPException:
            return None
