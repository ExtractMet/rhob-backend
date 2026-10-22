"""Audit logging helper (who did what, old/new values, reasons). No unnecessary personal data:
only the account name and role are stored."""
from __future__ import annotations

import logging

from ..data import repositories as repo

log = logging.getLogger("rhob.audit")


def record(principal, action: str, target: str = "", **detail):
    try:
        repo.audit(principal.user, principal.role, action, target, detail)
    except Exception as exc:  # audit failure is logged, never silently ignored
        log.error("audit write failed: %s", exc)
    log.info("audit", extra={"user": principal.user, "role": principal.role, "event": action})
