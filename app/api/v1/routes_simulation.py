from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, Header, Query, Response

from ...core.config import SYNTHETIC_BANNER
from ...core.errors import NotFound, PreconditionFailed, ValidationFailed
from ...core.jsonsafe import SafeJSONResponse, clean
from ...core.security import Principal, current_principal, require
from ...data import repositories as repo
from ...estimation.uncertainty import ensemble, sample_kinetics
from ...orchestration.scenarios import SCENARIO_DESCRIPTIONS, build_scenario
from ...orchestration.simulation_runner import MANAGER, SimulationSession
from ...physics import mixing
from ...physics.solver import RHOBModel
from ...physics.state_vector import ENERGY_TERMS, SINK_TERMS, SOURCE_TERMS
from ...schemas.configuration import GeometryConfig, KineticsConfig, PlantConfig, SimulationRequest
from ...schemas.simulation import CompareRequest, LabResult, ResumeRequest, SimulationCreate, StepRequest
from ...services.audit import record
from ...services.reporting import evaluate_endpoint, compute_kpis
from ...services.validation import validity_domain_issues
from ...physics.geometry import preset_for_capacity
from ...workers import jobs

router = APIRouter(prefix="/api/v1", tags=["simulations"], default_response_class=SafeJSONResponse)


def _etag(s: SimulationSession) -> str:
    return f'W/"{s.sim_id}-{s.version}"'


def _check_if_match(s, if_match):
    if if_match and if_match != _etag(s):
        raise PreconditionFailed("stale scenario version (ETag mismatch) - reload and retry", {"current": _etag(s)})


@router.post("/simulations", status_code=201, summary="Create a simulation (typed request or named synthetic scenario)")
def create_simulation(body: SimulationCreate, response: Response, p: Principal = Depends(require("Operator")),
                      idempotency_key: str | None = Header(default=None)):
    if idempotency_key:
        prev = repo.idem_get(f"sim:{idempotency_key}")
        if prev:
            response.headers["Idempotent-Replay"] = "true"
            return prev
    if body.scenario:
        if body.scenario not in SCENARIO_DESCRIPTIONS:
            raise NotFound(f"unknown scenario {body.scenario}")
        req = build_scenario(body.scenario)
    else:
        req = body.request
    if body.capacity_t is not None:
        pre = preset_for_capacity(body.capacity_t)
        g = GeometryConfig.from_capacity(body.capacity_t)
        g.ladle_wall_layers = req.plant.geometry.ladle_wall_layers
        g.vessel_wall_layers = req.plant.geometry.vessel_wall_layers
        g.oxygen_tuyere_count = req.plant.geometry.oxygen_tuyere_count
        req.plant.geometry = g
        req.plant.vacuum.pump_curve = pre["pump_curve"]
        req.plant.limits.oxygen_max_Nm3_h = round(pre["oxygen_max_Nm3_h"])
        req.plant.limits.argon_max_NL_min = round(1.3 * pre["argon_nominal_NL_min"])
        if body.request is not None and req.schedule is None:
            pass
    if body.request is not None and req.plant.kinetics != KineticsConfig() and not p.has("ProcessEngineer"):
        raise ValidationFailed("changing kinetic/calibration parameters requires ProcessEngineer role")
    issues = validity_domain_issues(req)
    if any(i["severity"] == "error" for i in issues):
        raise ValidationFailed("input outside model validity domain", {"issues": issues})
    s = MANAGER.create(req, user=p.user, run_to_end=body.run_to_end)
    record(p, "SIMULATION_CREATE", s.sim_id, scenario=req.scenario_name, mode=req.mode.value, heat=req.heat.heat_id)
    out = s.summary()
    out["validity_issues"] = issues
    response.headers["ETag"] = _etag(s)
    if idempotency_key:
        repo.idem_put(f"sim:{idempotency_key}", clean(out))
    return out


@router.post("/simulations/validate", summary="Validate inputs without creating a simulation")
def validate(req: SimulationRequest, p: Principal = Depends(current_principal)):
    from ...orchestration.scenarios import grade_by_id, standard_schedule
    from ...orchestration.state_machine import validate_schedule
    grade = req.grade or grade_by_id(req.heat.grade_id)
    sched = req.schedule or standard_schedule(req.plant, req.heat, grade)
    iss = [{"severity": i.severity, "message": i.message} for i in validate_schedule(sched, req.plant)]
    iss += validity_domain_issues(req)
    return {"valid": not any(i["severity"] == "error" for i in iss), "issues": iss,
            "schedule": sched.model_dump(mode="json")}


@router.get("/simulations", summary="List simulations (paginated)")
def list_simulations(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), heat_id: str | None = None,
                     p: Principal = Depends(current_principal)):
    return {"items": repo.list_simulations(limit, offset, heat_id), "limit": limit, "offset": offset,
            "live_sessions": list(MANAGER.sessions.keys())}


@router.get("/simulations/{sim_id}", summary="Simulation summary (status, state, KPIs, alarms, advisories)")
def get_simulation(sim_id: str, response: Response, heavy: bool = False, p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    response.headers["ETag"] = _etag(s)
    return s.summary(include_heavy=heavy)


@router.post("/simulations/{sim_id}/step", summary="Advance the simulation clock")
def step(sim_id: str, body: StepRequest, response: Response, p: Principal = Depends(require("Operator")),
         if_match: str | None = Header(default=None)):
    s = MANAGER.get(sim_id)
    _check_if_match(s, if_match)
    s.step(dt_s=body.dt_s, to_s=body.to_s)
    response.headers["ETag"] = _etag(s)
    return s.summary()


@router.post("/simulations/{sim_id}/pause", summary="Pause (freezes the simulation clock)")
def pause(sim_id: str, p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(sim_id)
    s.pause()
    record(p, "SIMULATION_PAUSE", sim_id, t=s.t)
    return {"simulation_id": sim_id, "status": s.status, "sim_time_s": s.t, "version": s.version}


@router.post("/simulations/{sim_id}/resume", summary="Resume (optionally auto-play at speed x)")
def resume(sim_id: str, body: ResumeRequest = ResumeRequest(), p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(sim_id)
    s.resume(body.speed)
    record(p, "SIMULATION_RESUME", sim_id, speed=body.speed)
    return {"simulation_id": sim_id, "status": s.status, "sim_time_s": s.t, "speed": s.speed, "version": s.version}


@router.post("/simulations/{sim_id}/reset", summary="Reset to t = 0 (same request, same seed)")
def reset(sim_id: str, p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(sim_id)
    s.reset()
    record(p, "SIMULATION_RESET", sim_id)
    return {"simulation_id": sim_id, "status": s.status, "sim_time_s": s.t, "version": s.version}


@router.get("/simulations/{sim_id}/trajectory", summary="Time trajectory (paginated by index, selectable fields)")
def trajectory(sim_id: str, fields: str | None = Query(None, description="comma separated field names"),
               since_index: int = Query(0, ge=0), stride: int = Query(1, ge=1, le=100), kind: str = Query("twin"),
               limit: int = Query(5000, ge=1, le=20000), p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    model = s.twin if kind == "twin" else s.plant
    if model is None:
        raise NotFound("no plant-truth trajectory for this simulation")
    recs = model.records[since_index::stride][:limit]
    if fields:
        fl = ["t_s", "stage"] + [f for f in fields.split(",") if f]
        recs = [{k: r.get(k) for k in fl} for r in recs]
    return {"simulation_id": sim_id, "kind": kind, "n_total": len(model.records), "since_index": since_index,
            "records": recs, "banner": SYNTHETIC_BANNER, "events": model.events}


@router.post("/simulations/{sim_id}/lab-results", summary="Apply a (delayed) lab result: twin state reconciliation")
def lab_results(sim_id: str, body: LabResult, p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(sim_id)
    rec = s.apply_lab_result(body.values, body.t_sample_s, body.source, p.user)
    record(p, "LAB_RESULT_APPLIED", sim_id, t_sample=body.t_sample_s, values=body.values, source=body.source, reason=body.reason)
    return rec


@router.get("/simulations/{sim_id}/lab-results", summary="Lab results (synthetic plant) with availability")
def get_lab_results(sim_id: str, p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    return {"items": s.available_lab_results(), "assimilations": s.assimilations}


@router.get("/simulations/{sim_id}/forecast", summary="Forecast to end of schedule from current state with prediction bands")
def forecast(sim_id: str, p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    return s.forecast(store=True)


@router.get("/simulations/{sim_id}/estimator", summary="EKF soft-sensor trace vs synthetic plant truth")
def estimator(sim_id: str, p: Principal = Depends(current_principal)):
    return MANAGER.get(sim_id).estimator()


@router.get("/simulations/{sim_id}/ledger", summary="Energy & element ledgers (per time step and cumulative)")
def ledger(sim_id: str, p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    m = s.twin
    rows = []
    for r in m.records:
        rows.append({"t_s": r["t_s"], **{k: r.get(f"E_{k}_MJ") for k in ENERGY_TERMS},
                     "E_stored_change_MJ": r.get("E_stored_change_MJ"), "E_ledger_net_MJ": r.get("E_ledger_net_MJ"),
                     "energy_residual_MJ": r.get("energy_balance_residual_MJ"),
                     "mass_rel_err": r.get("mass_balance_relative_error")})
    return {"energy_terms": ENERGY_TERMS, "source_terms": SOURCE_TERMS, "sink_terms": SINK_TERMS, "rows": rows,
            "element_ledger_kg": m.closure.element_ledger(m.y), "closure_ok": m.closure.ok, "message": m.closure.message(),
            "corrections": getattr(m.closure, "corrections", []), "state_layout": m.L.describe()}


@router.get("/simulations/{sim_id}/mixing", summary="Mixing analysis: 95 % mixing time and tracer response at a time")
def mixing_analysis(sim_id: str, t_s: float | None = None, p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    recs = [r for r in s.twin.records if (r.get("q_circ_kg_s") or 0) > 0]
    if not recs:
        return {"available": False, "reason": "no circulation yet"}
    r = min(recs, key=lambda q: abs(q["t_s"] - (t_s if t_s is not None else recs[-1]["t_s"])))
    resp = mixing.tracer_response(r["M_l_kg"], r["M_d_kg"], r["M_v_kg"], r["q_circ_kg_s"], r["q_exchange_kg_s"], 600, 121)
    sd = s.req.plant.kinetics.circulation_multiplier_sd
    t95 = r.get("mixing_time_95_s")
    return {"available": True, "t_s": r["t_s"], "q_circ_t_min": r["q_circ_t_min"], "mixing_time_95_s": t95,
            "mixing_time_95_CI_s": [t95 / (1 + 1.96 * sd), t95 / max(1 - 1.96 * sd, 0.2)] if t95 else None,
            "recirculation_number": r.get("recirculation_number"), "tracer": resp}


@router.get("/simulations/{sim_id}/visual", summary="Geometry + state packets bound to the 3D view")
def visual(sim_id: str, stride: int = Query(1, ge=1, le=50), p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    m = s.twin
    g = s.req.plant.geometry
    dg = m.dg
    keys = ["t_s", "stage", "P_Pa", "argon_NL_min", "oxygen_Nm3_h", "q_circ_t_min", "T_l_K", "T_v_K", "T_bulk_K", "vessel_depth_m",
            "ladle_level_drop_m", "x_CO", "x_Ar", "C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm", "Al_bulk_ppm", "o2_abs_eff",
            "T_ladle_hotface_K", "T_vlow_hotface_K", "T_vup_hotface_K", "T_ladle_shell_K", "T_vlow_shell_K", "T_slag_K",
            "offgas_CO_Nm3_h", "surface_factor", "u_downleg_m_s", "mixing_time_95_s", "inner_site_depth_m", "superheat_K",
            "total_O_ppm", "pump_throttle", "M_v_kg"]
    pk = [{k: r.get(k) for k in keys} for r in m.records[::stride]]
    return {"geometry": {"ladle_D": g.ladle_inner_diameter_m, "ladle_bath_depth": dg.bath_depth_ladle, "freeboard": g.ladle_freeboard_m,
                         "ladle_lining": sum(l.thickness_m for l in g.ladle_wall_layers),
                         "snorkel_D": g.snorkel_inner_diameter_m, "snorkel_L": g.snorkel_length_m, "snorkel_wall": g.snorkel_wall_thickness_m,
                         "immersion": g.immersion_depth_m, "vessel_D": g.vessel_inner_diameter_m, "vessel_H": g.vessel_height_m,
                         "vessel_lower_H": g.vessel_lower_height_m, "vessel_lining": sum(l.thickness_m for l in g.vessel_wall_layers),
                         "tuyere_count": g.oxygen_tuyere_count, "tuyere_h": g.oxygen_tuyere_height_above_bottom_m,
                         "nozzles": g.lift_nozzle_count, "nozzle_h": g.lift_nozzle_height_above_tip_m, "h_vb0": dg.h_vb0,
                         "capacity_t": g.capacity_t, "variant": s.req.plant.variant.value},
            "packets": pk, "schematic_note": "Schematic visualization bound to model state - NOT a CFD volume render",
            "banner": SYNTHETIC_BANNER}


@router.post("/simulations/{sim_id}/ensemble", status_code=202, summary="Ensemble uncertainty (background job)")
def run_ensemble(sim_id: str, n: int = Query(8, ge=3, le=30), p: Principal = Depends(require("Operator"))):
    s = MANAGER.get(sim_id)
    req = s.req

    def fn(progress):
        cnt = {"i": 0}

        def factory(rng):
            cnt["i"] += 1
            progress(cnt["i"] / n, f"member {cnt['i']}/{n}")
            kin = sample_kinetics(req.plant.kinetics, rng)
            return RHOBModel(req.plant, req.heat, s.schedule, req.solver.model_copy(update={"rtol": 1e-5, "record_interval_s": 30}),
                             s.grade, kin_overrides=kin, guard=s.twin.guard, label="ensemble")
        return ensemble(factory, n, req.solver.seed + 99)
    jid = jobs.submit("ensemble", fn, sim_id)
    return {"job_id": jid, "status": "accepted", "poll": f"/api/v1/jobs/{jid}"}


@router.post("/scenarios/compare", status_code=202, summary="Compare scenarios (background job, 202 + job_id)")
def compare(body: CompareRequest, p: Principal = Depends(require("Viewer"))):
    if len(body.scenarios) + len(body.requests) + len(body.simulation_ids) < 2:
        raise ValidationFailed("compare needs at least two scenarios/requests/simulation_ids")
    for sid in body.simulation_ids:
        MANAGER.get(sid)

    def fn(progress):
        out = []
        items = [("scenario", n) for n in body.scenarios] + [("request", r) for r in body.requests] + [("sim", s) for s in body.simulation_ids]
        for i, (kind, item) in enumerate(items):
            progress(i / len(items), f"running {i+1}/{len(items)}")
            if kind == "sim":
                ss = MANAGER.get(item)
                if ss.status != "completed":
                    ss = copy.deepcopy(ss) if False else ss
                    ss.run_to_end()
            else:
                req = build_scenario(item) if kind == "scenario" else item
                ss = SimulationSession(req, user=p.user)
                ss.run_to_end()
                MANAGER.sessions[ss.sim_id] = ss
            recs = ss.twin.records
            out.append({"name": ss.req.scenario_name, "simulation_id": ss.sim_id,
                        "endpoint": evaluate_endpoint(recs, ss.grade, ss.req.plant),
                        "kpis": compute_kpis(recs, ss.req.plant, ss.twin.applied_additions, ss.req.heat.steel_mass_t),
                        "closure": {"mass": ss.twin.closure.max_rel_mass, "energy": ss.twin.closure.max_rel_energy},
                        "trajectory": [{k: r.get(k) for k in ("t_s", "stage", "C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm",
                                                               "T_bulk_K", "P_Pa", "q_circ_t_min", "oxygen_Nm3_h", "offgas_CO_Nm3_h",
                                                               "Al_bulk_ppm", "total_O_ppm")} for r in recs]})
        return {"comparison": out}
    jid = jobs.submit("compare", fn)
    record(p, "SCENARIO_COMPARE", jid, scenarios=body.scenarios, n_requests=len(body.requests))
    return {"job_id": jid, "status": "accepted", "poll": f"/api/v1/jobs/{jid}"}


@router.get("/jobs/{job_id}", summary="Poll a background job")
def get_job(job_id: str, p: Principal = Depends(current_principal)):
    j = jobs.get(job_id)
    if j is None:
        raise NotFound(f"job {job_id} not found")
    return j
