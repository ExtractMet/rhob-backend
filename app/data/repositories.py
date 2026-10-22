"""Repository functions (persistence of heats, simulations, trajectories, audit)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .db import session
from .models import Alarm, AuditLog, Heat, IdempotencyKey, LabSample, OptimizationJob, Recommendation, Simulation, Trajectory


def save_heat(plant_id, heat_id, grade_id, payload, user="system", provenance="SYNTHETIC") -> int:
    with session() as s:
        h = Heat(plant_id=plant_id, heat_id=heat_id, grade_id=grade_id, payload=payload, created_by=user, provenance=provenance)
        s.add(h)
        s.flush()
        return h.id


def get_heat(heat_id: str) -> Optional[dict]:
    with session() as s:
        h = s.execute(select(Heat).where(Heat.heat_id == heat_id).order_by(Heat.id.desc())).scalars().first()
        if not h:
            return None
        return {"heat_id": h.heat_id, "plant_id": h.plant_id, "grade_id": h.grade_id, "payload": h.payload,
                "provenance": h.provenance, "created_at": h.created_at.isoformat(), "created_by": h.created_by}


def list_heats(limit=50, offset=0):
    with session() as s:
        rows = s.execute(select(Heat).order_by(Heat.id.desc()).limit(limit).offset(offset)).scalars().all()
        return [{"heat_id": h.heat_id, "grade_id": h.grade_id, "created_at": h.created_at.isoformat()} for h in rows]


def upsert_simulation(sim: dict, twin_records=None, plant_records=None):
    with session() as s:
        row = s.get(Simulation, sim["simulation_id"])
        if row is None:
            row = Simulation(**sim)
            s.add(row)
        else:
            for k, v in sim.items():
                setattr(row, k, v)
        s.flush()
        for kind, recs in (("twin", twin_records), ("plant", plant_records)):
            if recs is None:
                continue
            tr = s.execute(select(Trajectory).where(Trajectory.simulation_id == sim["simulation_id"], Trajectory.kind == kind)).scalars().first()
            if tr is None:
                s.add(Trajectory(simulation_id=sim["simulation_id"], kind=kind, records=recs))
            else:
                tr.records = recs


def get_simulation_row(sim_id: str) -> Optional[dict]:
    with session() as s:
        r = s.get(Simulation, sim_id)
        if r is None:
            return None
        return {c.name: getattr(r, c.name) for c in Simulation.__table__.columns}


def list_simulations(limit=50, offset=0, heat_id: Optional[str] = None):
    with session() as s:
        q = select(Simulation).order_by(Simulation.created_at.desc())
        if heat_id:
            q = q.where(Simulation.heat_id == heat_id)
        rows = s.execute(q.limit(limit).offset(offset)).scalars().all()
        return [{"simulation_id": r.simulation_id, "heat_id": r.heat_id, "scenario_name": r.scenario_name, "status": r.status,
                 "mode": r.mode, "sim_time_s": r.sim_time_s, "created_at": r.created_at.isoformat(),
                 "result_checksum": r.result_checksum} for r in rows]


def get_trajectory(sim_id: str, kind="twin"):
    with session() as s:
        tr = s.execute(select(Trajectory).where(Trajectory.simulation_id == sim_id, Trajectory.kind == kind)).scalars().first()
        return tr.records if tr else None


def add_lab_sample(sim_id, heat_id, t_s, t_a, values, source, applied=False):
    with session() as s:
        s.add(LabSample(simulation_id=sim_id, heat_id=heat_id, t_sample_s=t_s, t_available_s=t_a, values=values,
                        source=source, applied=applied))


def save_alarms(sim_id, alarms):
    with session() as s:
        for a in alarms:
            s.add(Alarm(simulation_id=sim_id, t_s=a["t_s"], hazard_id=a["id"], severity=a["severity"], message=a["message"]))


def list_alarms(sim_id: Optional[str] = None, limit=200, offset=0):
    with session() as s:
        q = select(Alarm).order_by(Alarm.id.desc())
        if sim_id:
            q = q.where(Alarm.simulation_id == sim_id)
        rows = s.execute(q.limit(limit).offset(offset)).scalars().all()
        return [{"simulation_id": r.simulation_id, "t_s": r.t_s, "id": r.hazard_id, "severity": r.severity, "message": r.message,
                 "acknowledged_by": r.acknowledged_by, "created_at": r.created_at.isoformat()} for r in rows]


def save_recommendations(sim_id, cards):
    with session() as s:
        for c in cards:
            s.add(Recommendation(simulation_id=sim_id, payload=c))


def save_optimization(job_id, sim_id, status, result):
    with session() as s:
        row = s.get(OptimizationJob, job_id)
        if row is None:
            s.add(OptimizationJob(job_id=job_id, simulation_id=sim_id, status=status, result=result))
        else:
            row.status = status
            row.result = result


def get_optimization(job_id):
    with session() as s:
        r = s.get(OptimizationJob, job_id)
        return None if r is None else {"job_id": r.job_id, "simulation_id": r.simulation_id, "status": r.status, "result": r.result}


def audit(user, role, action, target="", detail=None):
    with session() as s:
        s.add(AuditLog(user=user, role=role, action=action, target=target, detail=detail or {}))


def list_audit(limit=100, offset=0):
    with session() as s:
        rows = s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)).scalars().all()
        return [{"ts": r.ts.isoformat(), "user": r.user, "role": r.role, "action": r.action, "target": r.target, "detail": r.detail}
                for r in rows]


def idem_get(key):
    with session() as s:
        r = s.get(IdempotencyKey, key)
        return r.response if r else None


def idem_put(key, response):
    with session() as s:
        if s.get(IdempotencyKey, key) is None:
            s.add(IdempotencyKey(key=key, response=response))
