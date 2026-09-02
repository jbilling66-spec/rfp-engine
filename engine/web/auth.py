"""Operator identity (B37/D17): declared | header, chosen once at app
construction from config/web.yaml.

Declared mode is the pre-A5 reality — the operator declares a name AND a
role, a token cookie carries them, and they land in exactly the fields
the headless contracts fill (gate actor, waived_by, event actor and
actor_role), so decision artifacts do not change shape when the identity
source swaps to the A5 SSO proxy. Header mode is that seam: identity
comes from a reverse proxy that authenticates and SETS the headers
(stripping any client-supplied copy); /api/session is disabled.

The role is the session's, never the payload's (P27 wave 1, M-9): effort
and cost aggregate by role, and a hardcoded or client-chosen role
mis-attributes the one evidence stream the pilot exists to collect. The
role header is required only by the doors that record a role, so a
proxy that sets the user header alone still drives every other door.

Every MUTATING route requires an operator; reads are open (127.0.0.1
bind). Sessions are in-memory by design: lost on restart, which is the
honest lifetime of a declared identity. (v1 keeper design, reimplemented.)
"""

import secrets
from pathlib import Path

import yaml
from fastapi import HTTPException, Request

from engine.web.events import ACTOR_ROLES

_CONFIG_DEFAULT = Path(__file__).resolve().parents[2] / "config" / "web.yaml"

# The roles an operator may declare — the feedback-event enum minus the
# guest role, which only the share-link door assigns (D16a).
DECLARABLE_ROLES = tuple(r for r in ACTOR_ROLES if r != "external_reviewer")


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
        self.role_header_name = auth.get("role_header_name", "X-Auth-Role")
        self._sessions: dict[str, dict] = {}

    # -- declared mode ---------------------------------------------------

    def establish(self, name: str, role: str) -> str:
        if self.mode != "declared":
            raise HTTPException(
                400, "identity comes from the SSO proxy in header mode — "
                     "/api/session is disabled")
        name = " ".join(str(name).split())
        if not 2 <= len(name) <= 60:
            raise HTTPException(422, "operator name must be 2-60 characters")
        if role not in DECLARABLE_ROLES:
            raise HTTPException(
                422, f"role must be one of {DECLARABLE_ROLES} — effort and "
                     "cost aggregate by role")
        token = secrets.token_urlsafe(24)
        self._sessions[token] = {"name": name, "role": role}
        return token

    # -- the dependencies ---------------------------------------------------

    def _session(self, request: Request) -> dict:
        token = (request.cookies.get("operator")
                 or request.headers.get("x-operator-token"))
        session = self._sessions.get(token or "")
        if not session:
            raise HTTPException(
                401, "no operator session — declare who you are first "
                     "(POST /api/session)")
        return session

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
        return self._session(request)["name"]

    def role(self, request: Request) -> str:
        """The actor's role for a door that records one. Header mode:
        the proxy's role header (A5 sets it beside the user header);
        declared mode: the role declared at sign-in."""
        if self.mode == "header":
            role = " ".join(
                (request.headers.get(self.role_header_name) or "").split())
            if not role:
                raise HTTPException(
                    401, f"no {self.role_header_name} header — this door "
                         "records the actor's role, and the SSO reverse "
                         "proxy is expected to set it")
            if role not in DECLARABLE_ROLES:
                raise HTTPException(
                    422, f"{self.role_header_name} must be one of "
                         f"{DECLARABLE_ROLES}")
            return role
        return self._session(request)["role"]

    def whoami(self, request: Request) -> dict:
        """{operator, role} — None for both when nobody is signed in;
        in header mode the role is None until a role door needs it."""
        try:
            name = self.operator(request)
        except HTTPException:
            return {"operator": None, "role": None}
        role = None
        if self.mode == "header":
            header = request.headers.get(self.role_header_name) or ""
            role = " ".join(header.split()) or None
        else:
            role = self._session(request)["role"]
        return {"operator": name, "role": role}
