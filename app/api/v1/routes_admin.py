from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...core.config import get_settings
from ...core.errors import Forbidden, NotFound
from ...core.jsonsafe import SafeJSONResponse
from ...core.security import DEMO_ACCOUNTS, Principal, current_principal, issue_token, require
from ...data import repositories as repo
from ...orchestration.simulation_runner import MANAGER
from ...services.alerts import evaluate_alarms
from ...services.audit import record

router = APIRouter(prefix="/api/v1", tags=["admin"], default_response_class=SafeJSONResponse)


class DemoLogin(BaseModel):
    account: str


@router.post("/auth/demo-login", summary="DEMO ONLY: obtain a role token for a local demo account")
def demo_login(body: DemoLogin):
    if not get_settings().demo_auth:
        raise Forbidden("demo authentication disabled (RHOB_DEMO_AUTH=false); use the site identity provider")
    role = DEMO_ACCOUNTS.get(body.account)
    if role is None:
        raise NotFound("unknown demo account")
    tok = issue_token(body.account, role)
    record(Principal(body.account, role), "LOGIN_DEMO")
    return {"token": tok, "user": body.account, "role": role, "note": "demo token - not for production"}


@router.get("/auth/me", summary="Current principal")
def me(p: Principal = Depends(current_principal)):
    return {"user": p.user, "role": p.role}


@router.get("/alarms", summary="Alarms (live sessions evaluated; persisted list)")
def alarms(simulation_id: str | None = None, limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
           p: Principal = Depends(current_principal)):
    if simulation_id:
        s = MANAGER.get(simulation_id)
        return {"items": evaluate_alarms(s.twin.records, s.req.plant, s.twin.closure.ok), "source": "live evaluation"}
    items = []
    for s in MANAGER.sessions.values():
        for a in evaluate_alarms(s.twin.records, s.req.plant, s.twin.closure.ok):
            items.append({**a, "simulation_id": s.sim_id})
    return {"items": items[offset: offset + limit], "total": len(items)}


class Ack(BaseModel):
    simulation_id: str
    hazard_id: str
    t_s: float
    comment: str = ""


@router.post("/alarms/ack", summary="Acknowledge an alarm (logged)")
def ack(body: Ack, p: Principal = Depends(require("Operator"))):
    record(p, "ALARM_ACK", body.simulation_id, hazard=body.hazard_id, t=body.t_s, comment=body.comment)
    return {"acknowledged": True, "by": p.user}


class AdviceDecision(BaseModel):
    simulation_id: str
    title: str
    decision: str  # accepted | rejected | deferred
    reason: str = ""


@router.post("/advice/decision", summary="Record operator decision on an advisory card (no plant command issued)")
def advice(body: AdviceDecision, p: Principal = Depends(require("Operator"))):
    record(p, "ADVICE_DECISION", body.simulation_id, title=body.title, decision=body.decision, reason=body.reason)
    return {"recorded": True}


@router.get("/audit", summary="Audit log (paginated)")
def audit(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), p: Principal = Depends(require("Metallurgist"))):
    return {"items": repo.list_audit(limit, offset), "limit": limit, "offset": offset}


@router.get("/admin/sessions", summary="Live sessions")
def sessions(p: Principal = Depends(require("ProcessEngineer"))):
    return [{"simulation_id": s.sim_id, "status": s.status, "t": s.t, "scenario": s.req.scenario_name, "user": s.user}
            for s in MANAGER.sessions.values()]


@router.delete("/admin/sessions/{sim_id}", summary="Evict a live session from memory (persisted copy kept)")
def evict(sim_id: str, p: Principal = Depends(require("Admin"))):
    MANAGER.sessions.pop(sim_id, None)
    record(p, "SESSION_EVICT", sim_id)
    return {"evicted": sim_id}
