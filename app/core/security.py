"""Role-based access (demo authentication) enforced in the BACKEND.

Demo mode issues HMAC-signed bearer tokens for explicit local demo accounts (no passwords
stored in code: the demo "login" only selects a role and is disabled when
RHOB_DEMO_AUTH=false). Production must replace this with managed IAM / OIDC behind an
approved gateway (docs/SECURITY.md). Token secret comes from RHOB_TOKEN_SECRET; if unset,
a random per-process secret is generated (tokens then expire at restart).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from fastapi import Depends, Header

from .config import get_settings
from .errors import Forbidden

ROLES = ["Viewer", "Operator", "Metallurgist", "ProcessEngineer", "Admin"]
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}
DEMO_ACCOUNTS = {"viewer": "Viewer", "operator": "Operator", "metallurgist": "Metallurgist",
                 "engineer": "ProcessEngineer", "admin": "Admin"}

_PROCESS_SECRET = secrets.token_hex(32)


def _secret() -> bytes:
    s = get_settings().token_secret or _PROCESS_SECRET
    return s.encode()


def issue_token(user: str, role: str, ttl_s: int = 12 * 3600) -> str:
    payload = {"u": user, "r": role, "exp": int(time.time()) + ttl_s}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".")
        good = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if payload["exp"] < time.time():
            return None
        return payload
    except Exception:
        return None


class Principal:
    def __init__(self, user: str, role: str):
        self.user = user
        self.role = role

    def has(self, min_role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[min_role]


def current_principal(authorization: Optional[str] = Header(default=None)) -> Principal:
    if authorization and authorization.lower().startswith("bearer "):
        p = verify_token(authorization[7:])
        if p:
            return Principal(p["u"], p["r"])
        raise Forbidden("invalid or expired token")
    return Principal("anonymous", "Viewer")


def require(min_role: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.has(min_role):
            raise Forbidden(f"role {p.role} insufficient; requires {min_role} or higher")
        return p
    return dep
