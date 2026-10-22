"""Simulation sessions: twin + synthetic plant, lifecycle, lab results, forecasts, persistence.

A session owns:
  * twin   : nominal-parameter RHOBModel (the digital twin whose state is estimated)
  * plant  : SYNTHETIC 'plant truth' RHOBModel with seeded perturbations of kinetics and of
             the arrival assay (stand-in for the real plant in DEMO_SYNTHETIC mode). It only
             produces MEASUREMENTS (lab results with noise & delay, thermocouple dips, off-gas).
Both advance in lock-step. Pause freezes the simulation clock (step requests are refused).
"""
from __future__ import annotations

import copy
import math
import threading
import time
import uuid
from typing import Optional

import numpy as np

from ..core.config import MODEL_VERSION, SYNTHETIC_BANNER, checksum, get_settings, source_hash
from ..core.errors import Conflict, NotFound, TooMany, ValidationFailed
from ..data import repositories as repo
from ..estimation.observer import ObserverConfig, run_filter
from ..estimation.reconciliation import LAB_SIGMA, assimilate
from ..estimation.uncertainty import analytic_bands, sample_kinetics
from ..physics.properties import MW
from ..physics.solver import RHOBModel
from ..schemas.configuration import HeatInput, Mode, SimulationRequest
from ..services.alerts import evaluate_alarms
from ..services.reporting import advisory_cards, compute_kpis, evaluate_endpoint, material_inputs_outputs
from .scenarios import grade_by_id, standard_schedule
from .state_machine import make_guard, validate_schedule

TRUTH_PERTURB = {"C": 0.04, "O": 0.06, "H": 0.10, "N": 0.05, "Al": 0.05}


class SimulationSession:
    def __init__(self, req: SimulationRequest, sim_id: Optional[str] = None, user: str = "system"):
        if req.mode == Mode.APPROVED_CLOSED_LOOP_EDGE_ONLY and not get_settings().closed_loop_feature:
            raise ValidationFailed("APPROVED_CLOSED_LOOP_EDGE_ONLY is feature-gated and disabled; it requires a separate "
                                   "certified on-premises integration project (docs/OT_INTEGRATION.md).")
        self.req = req
        self.sim_id = sim_id or f"sim-{uuid.uuid4().hex[:10]}"
        self.user = user
        self.grade = req.grade or grade_by_id(req.heat.grade_id)
        self.schedule = req.schedule or standard_schedule(req.plant, req.heat, self.grade)
        issues = validate_schedule(self.schedule, req.plant)
        errs = [i.message for i in issues if i.severity == "error"]
        if errs:
            raise ValidationFailed("schedule validation failed", {"errors": errs})
        self.validation_warnings = [i.message for i in issues if i.severity == "warning"]
        guard = make_guard(req.plant, self.grade)
        self.twin = RHOBModel(req.plant, req.heat, self.schedule, req.solver, self.grade, guard=guard, label="twin")
        self.rng = np.random.default_rng(req.solver.seed)
        self.plant = None
        if req.synthetic_plant_truth and req.mode in (Mode.DEMO_SYNTHETIC, Mode.OPERATOR_ADVISORY, Mode.SHADOW_ONLINE,
                                                      Mode.WHAT_IF, Mode.ENGINEERING_BATCH_SIMULATION):
            kin_p = sample_kinetics(req.plant.kinetics, np.random.default_rng(req.solver.seed + 7))
            # moderate the perturbation (plant differs from nominal model by ~1/2 of stated uncertainty)
            kin_p = {k: (getattr(req.plant.kinetics, k) * (v / getattr(req.plant.kinetics, k)) ** 0.5) for k, v in kin_p.items()}
            comp = dict(req.heat.composition_ppm)
            for k, s in TRUTH_PERTURB.items():
                if k in comp and comp[k] > 0:
                    comp[k] = comp[k] * float(np.exp(self.rng.normal(0, s)))
            heat_t = req.heat.model_copy(update={"composition_ppm": comp,
                                                 "T_arrival_K": req.heat.T_arrival_K + float(self.rng.normal(0, 3.0))})
            self.plant = RHOBModel(req.plant, heat_t, self.schedule, req.solver, self.grade, kin_overrides=kin_p,
                                   guard=guard, label="plant")
            self.plant_kinetics = kin_p
        self.lock = threading.RLock()
        self.paused = False
        self.version = 1
        self.lab_results: list[dict] = []
        self.measurements = {"offgas": [], "T": [], "C_lab": []}
        self.forecasts: list[dict] = []
        self.assimilations: list[dict] = []
        self.created = time.time()
        self.speed = 0.0  # real-time compression factor when playing via scheduler
        self.playing = False
        self.last_step_wall = time.time()
        self._persist()

    # ------------------------------------------------------------------ lifecycle
    @property
    def t(self):
        return self.twin.t

    @property
    def status(self):
        if self.twin.status == "failed":
            return "failed"
        if self.twin.t >= self.twin.t_end_schedule - 1e-6:
            return "completed"
        if self.paused:
            return "paused"
        if self.playing:
            return "running"
        return "ready" if self.twin.t == 0 else "stepped"

    def step(self, dt_s: Optional[float] = None, to_s: Optional[float] = None, persist=True) -> dict:
        with self.lock:
            if self.paused:
                raise Conflict("simulation is paused - resume before stepping (simulation clock frozen)")
            target = to_s if to_s is not None else self.twin.t + (dt_s if dt_s is not None else 60.0)
            target = min(target, self.twin.t_end_schedule)
            self.twin.step_to(target)
            if self.plant is not None:
                self.plant.step_to(target)
                self._synthesize_measurements()
            self.version += 1
            if persist:
                self._persist()
            return {"simulation_id": self.sim_id, "status": self.status, "sim_time_s": self.twin.t}

    def run_to_end(self):
        return self.step(to_s=self.twin.t_end_schedule)

    def pause(self):
        with self.lock:
            self.paused = True
            self.playing = False
            self.version += 1
            self.twin._event("PAUSE", "simulation clock frozen")
            self._persist()

    def resume(self, speed: float = 0.0):
        with self.lock:
            self.paused = False
            self.speed = speed
            self.playing = speed > 0
            self.last_step_wall = time.time()
            self.version += 1
            self.twin._event("RESUME", f"simulation resumed (speed x{speed})")
            self._persist()

    def reset(self):
        with self.lock:
            fresh = SimulationSession(self.req, self.sim_id, self.user)
            self.__dict__.update({k: v for k, v in fresh.__dict__.items() if k != "lock"})
            self.version += 1
            self._persist()

    # ------------------------------------------------------------------ measurements
    def _synthesize_measurements(self):
        p = self.plant
        # off-gas carbon removal rate measured at the pump: (CO + CO2) x exhaust, 20 s delay, 4 % noise
        seen = {round(t, 3) for t, _ in self.measurements["offgas"]}
        for r in p.records:
            if r["t_s"] in seen or r["t_s"] <= 0:
                continue
            exh = r.get("exhaust_mol_s") or 0.0
            n_c = ((r.get("x_CO") or 0) + (r.get("x_CO2") or 0)) * exh
            ppm_min = n_c * MW["C"] / max(r.get("M_total_kg") or 1, 1) * 1e6 * 60
            if r.get("q_circ_kg_s", 0) > 0:
                self.measurements["offgas"].append((r["t_s"] + 20.0, ppm_min * float(np.exp(self.rng.normal(0, 0.04)))))
        # lab results (plant samples) - noisy, delayed
        known = {(lr["t_sample_s"]) for lr in self.lab_results}
        for s in p.lab_samples:
            if s["t_sample_s"] in known:
                continue
            vals = {}
            for k, v in s["values_truth"].items():
                key = k.replace("_ppm", "").replace("_K", "")
                sig = LAB_SIGMA.get(key, 5.0)
                vals[k] = max(v + float(self.rng.normal(0, sig)), 0.0)
            lr = {"t_sample_s": s["t_sample_s"], "t_available_s": s["t_available_s"], "values": vals,
                  "truth": s["values_truth"], "source": "LAB ANALYZED (synthetic plant)", "applied": False,
                  "kinds": s["kinds"]}
            self.lab_results.append(lr)
            if "T_K" in vals:
                self.measurements["T"].append((s["t_sample_s"], vals["T_K"]))
            if "C_ppm" in vals:
                self.measurements["C_lab"].append((s["t_sample_s"], s["t_available_s"], vals["C_ppm"]))
            repo.add_lab_sample(self.sim_id, self.req.heat.heat_id, s["t_sample_s"], s["t_available_s"], vals, lr["source"])

    def available_lab_results(self) -> list[dict]:
        return [dict(lr, available=lr["t_available_s"] <= self.twin.t + 1e-6) for lr in self.lab_results]

    def apply_lab_result(self, values: dict, t_sample_s: float, source: str = "USER-DEFINED", user="system") -> dict:
        """Assimilate lab values into the twin state (delayed reconciliation)."""
        with self.lock:
            if t_sample_s > self.twin.t + 1e-6:
                raise ValidationFailed("sample time is in the future of the simulation clock")
            before = self.forecast(store=False)
            entries = []
            for k, v in values.items():
                kind = "T" if k in ("T", "T_K") else k.replace("_ppm", "")
                if kind not in ("C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "T"):
                    continue
                if v is None or (isinstance(v, float) and not math.isfinite(v)) or v < 0:
                    raise ValidationFailed(f"invalid lab value for {k}")
                if kind == "T" and not (1700 <= v <= 2000):
                    raise ValidationFailed("lab/thermocouple temperature outside physical range (K)")
                entries.append(assimilate(self.twin, kind, float(v), t_sample_s))
            for lr in self.lab_results:
                if abs(lr["t_sample_s"] - t_sample_s) < 1e-6:
                    lr["applied"] = True
            after = self.forecast(store=True)
            rec = {"t_applied_s": self.twin.t, "t_sample_s": t_sample_s, "source": source, "entries": entries,
                   "forecast_before": before["endpoint"], "forecast_after": after["endpoint"], "user": user}
            self.assimilations.append(rec)
            self.version += 1
            self._persist()
            return rec

    # ------------------------------------------------------------------ forecasts
    def forecast(self, store=True) -> dict:
        """Predict to schedule end from the CURRENT twin state (copy; does not advance the session)."""
        with self.lock:
            m = copy.deepcopy(self.twin)
            m.guard = self.twin.guard
            m.step_to(m.t_end_schedule)
            ep = evaluate_endpoint(m.records, self.grade, self.req.plant)
            bands = analytic_bands(m.records, self.twin.t, s_K=self.req.plant.kinetics.circulation_multiplier_sd)
            out = {"t_from_s": self.twin.t, "endpoint": ep, "bands": bands,
                   "trajectory": [{k: r.get(k) for k in ("t_s", "C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm",
                                                         "T_bulk_K", "Al_bulk_ppm", "stage")} for r in m.records if r["t_s"] >= self.twin.t]}
            if store:
                self.forecasts.append({"t_from_s": self.twin.t, "endpoint": {"C": ep["rh_end_state"]["C_bulk_ppm"],
                                                                             "T": ep["rh_end_state"]["T_bulk_K"],
                                                                             "H": ep["rh_end_state"]["H_bulk_ppm"],
                                                                             "N": ep["rh_end_state"]["N_bulk_ppm"],
                                                                             "feasible": ep["feasible"]}})
            return out

    def estimator(self) -> dict:
        if self.plant is None:
            return {"available": False, "reason": "no measurement source (synthetic plant disabled)"}
        res = run_filter(self.twin.records, self.measurements, ObserverConfig())
        res["available"] = True
        res["plant_truth"] = [{"t_s": r["t_s"], "C_ppm": r["C_bulk_ppm"], "O_ppm": r["O_bulk_ppm"], "T_K": r["T_bulk_K"]}
                              for r in self.plant.records]
        res["measurements"] = {"offgas": self.measurements["offgas"], "T": self.measurements["T"], "C_lab": self.measurements["C_lab"]}
        return res

    # ------------------------------------------------------------------ outputs
    def summary(self, include_heavy=False) -> dict:
        m = self.twin
        recs = m.records
        last = recs[-1]
        alarms = evaluate_alarms(recs, self.req.plant, m.closure.ok)
        complete = self.status == "completed"
        ep = evaluate_endpoint(recs, self.grade, self.req.plant) if recs else {}
        kp = compute_kpis(recs, self.req.plant, m.applied_additions, self.req.heat.steel_mass_t)
        mode = self.req.mode.value
        quality = "synthetic_valid" if (m.closure.ok and m.status != "failed") else "INVALID"
        inhibited = (not m.closure.ok) or m.status == "failed" or any(a["severity"] == "alarm" and a["inhibit"] == "ADVISORY_INHIBITED" for a in alarms)
        state = {
            "temperature_K": {"value": last["T_bulk_K"], "unit": "K", "source": "model", "quality": quality,
                              "CI95": [last["T_bulk_K"] - 6.0, last["T_bulk_K"] + 6.0], "provenance": "PREDICTED"},
            "vessel_pressure_Pa_abs": {"value": last["P_Pa"], "unit": "Pa_abs", "source": "model", "provenance": "PREDICTED"},
            "carbon_mass_fraction": {"value": last["C_bulk_ppm"] * 1e-6, "unit": "kg/kg", "source": "model", "provenance": "SOFT-SENSED"},
            "circulation_t_min": {"value": last["q_circ_t_min"], "unit": "t/min", "source": "model", "provenance": "ESTIMATED"},
        }
        warnings = [SYNTHETIC_BANNER] + list(self.validation_warnings) + list(m.warnings)
        if inhibited:
            warnings.append("ADVISORY_INHIBITED: model integrity/alarm condition - recommendations paused")
        out = {
            "simulation_id": self.sim_id, "heat_id": self.req.heat.heat_id, "grade_id": self.grade.grade_id if self.grade else None,
            "scenario_name": self.req.scenario_name, "mode": mode, "status": self.status, "sim_time_s": m.t,
            "t_end_schedule_s": m.t_end_schedule, "quality": quality, "state": state,
            "mass_balance_relative_error": m.closure.max_rel_mass, "energy_balance_relative_error": m.closure.max_rel_energy,
            "closure_worst_element": m.closure.worst_element, "warnings": warnings, "model_version": MODEL_VERSION,
            "version": self.version, "paused": self.paused, "playing": self.playing, "speed": self.speed,
            "endpoint_current_trajectory": ep, "kpis": kp, "alarms": alarms, "advisory_inhibited": inhibited,
            "events": m.events + ([dict(e, source="plant") for e in self.plant.events if e["kind"] in ("TRANSITION_BLOCKED",)] if self.plant else []),
            "lab_results": self.available_lab_results(), "assimilations": self.assimilations, "forecasts": self.forecasts,
            "solver_stats": m.solver_stats, "phase_table": [{k: ph[k] for k in ("index", "stage", "t_start", "t_end", "pressure_setpoint_Pa",
                                                                               "pressure_setpoint_end_Pa", "argon_NL_min", "oxygen_Nm3_h", "blocked",
                                                                               "block_reason", "snorkels_immersed", "vent")} for ph in m.phase_table],
            "applied_additions": m.applied_additions, "reproducibility": self.reproducibility(),
            "maturity_gate": "A (software complete - engineering demonstration; NOT plant validated)",
        }
        out["advisories"] = advisory_cards(recs, self.grade, self.req.plant, ep, alarms, mode, m.t) if complete else []
        if include_heavy:
            out["material_io"] = material_inputs_outputs(m)
            out["closure_corrections"] = getattr(m.closure, "corrections", [])
        return out

    def reproducibility(self) -> dict:
        s = get_settings()
        return {"scenario_id": self.req.scenario_id or self.req.scenario_name, "config_version": self.req.plant.config_version,
                "source_hash": source_hash()[:16], "backend_git_sha": s.git_sha, "seed": self.req.solver.seed,
                "request_checksum": checksum(self.req.model_dump(mode="json"))[:16],
                "result_checksum": checksum([(r["t_s"], round(r["C_bulk_ppm"], 6), round(r["T_bulk_K"], 6)) for r in self.twin.records])[:16],
                "created_unix": self.created, "model_version": MODEL_VERSION}

    def _persist(self):
        try:
            repro = self.reproducibility()
            repo.upsert_simulation({
                "simulation_id": self.sim_id, "plant_id": self.req.plant.plant_id, "heat_id": self.req.heat.heat_id,
                "mode": self.req.mode.value, "scenario_name": self.req.scenario_name, "status": self.status,
                "request": self.req.model_dump(mode="json"), "summary": {"t": self.twin.t, "paused": self.paused},
                "sim_time_s": self.twin.t, "version": self.version, "model_version": MODEL_VERSION,
                "config_version": self.req.plant.config_version, "source_hash": repro["source_hash"],
                "git_sha": repro["backend_git_sha"], "seed": self.req.solver.seed, "result_checksum": repro["result_checksum"],
                "created_by": self.user}, self.twin.records, self.plant.records if self.plant else None)
        except Exception as exc:  # persistence failure must not corrupt the in-memory twin
            self.twin.warnings.append(f"persistence failed: {exc}")


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, SimulationSession] = {}
        self.lock = threading.RLock()

    def create(self, req: SimulationRequest, user="system", run_to_end=False) -> SimulationSession:
        with self.lock:
            if len(self.sessions) >= get_settings().max_sessions:
                # evict oldest completed sessions (they remain persisted in the DB)
                done = sorted([s for s in self.sessions.values() if s.status in ("completed", "failed")], key=lambda s: s.created)
                for s in done[: max(1, len(done) // 2)]:
                    self.sessions.pop(s.sim_id, None)
                if len(self.sessions) >= get_settings().max_sessions:
                    raise TooMany("maximum concurrent simulations reached")
        s = SimulationSession(req, user=user)
        with self.lock:
            self.sessions[s.sim_id] = s
        if run_to_end:
            s.run_to_end()
        return s

    def get(self, sim_id: str) -> SimulationSession:
        s = self.sessions.get(sim_id)
        if s is not None:
            return s
        row = repo.get_simulation_row(sim_id)
        if row is None:
            raise NotFound(f"simulation {sim_id} not found")
        # deterministic restoration from the persisted request (backend restart)
        req = SimulationRequest(**row["request"])
        s = SimulationSession(req, sim_id=sim_id, user=row.get("created_by", "system"))
        if row["sim_time_s"] > 0:
            s.step(to_s=row["sim_time_s"])
        with self.lock:
            self.sessions[sim_id] = s
        return s


MANAGER = SessionManager()
