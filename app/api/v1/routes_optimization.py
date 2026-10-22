from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.errors import NotFound
from ...core.jsonsafe import SafeJSONResponse
from ...core.security import Principal, current_principal, require
from ...optimization.mpc import AdvisoryOptimizer
from ...physics.solver import RHOBModel
from ...orchestration.simulation_runner import MANAGER
from ...schemas.simulation import OptimizationRequest
from ...services.audit import record
from ...workers import jobs

router = APIRouter(prefix="/api/v1", tags=["optimization"], default_response_class=SafeJSONResponse)


@router.post("/optimization", status_code=202, summary="Request constrained advisory optimization (202 + job_id)")
def optimize(body: OptimizationRequest, p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(body.simulation_id)

    def fn(progress):
        with s.lock:
            deep_over = any(p["stage"] == "DEEP_VACUUM" and p["t_end"] <= s.twin.t for p in s.twin.phase_table)
            from_start = body.from_start if body.from_start is not None else deep_over
            if from_start:
                base = RHOBModel(s.req.plant, s.req.heat, s.schedule, s.req.solver, s.grade, guard=s.twin.guard, label="plan")
            else:
                base = s.twin
            opt = AdvisoryOptimizer(base, s.req.plant, s.grade, budget_s=body.budget_s, max_iter=body.max_iter, progress=progress)
        res = opt.run()
        res["horizon"] = "whole heat re-planned from t = 0 (pre-heat planning)" if from_start else f"receding horizon from t = {s.twin.t:.0f} s"
        res["from_sim_time_s"] = 0.0 if from_start else s.twin.t
        res["simulation_id"] = s.sim_id
        res["mode"] = s.req.mode.value
        res["note"] = "ADVISORY ONLY - requires operator acknowledgement; no plant command is issued"
        return res
    jid = jobs.submit("opt", fn, s.sim_id)
    record(p, "OPTIMIZATION_REQUEST", s.sim_id, job_id=jid, budget_s=body.budget_s)
    return {"job_id": jid, "status": "accepted", "poll": f"/api/v1/optimizations/{jid}"}


@router.get("/optimizations/{job_id}", summary="Optimization job status / result")
def get_opt(job_id: str, p: Principal = Depends(current_principal)):
    j = jobs.get(job_id)
    if j is None:
        raise NotFound(f"job {job_id} not found")
    return j
