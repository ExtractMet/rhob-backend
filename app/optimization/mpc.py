"""Receding-horizon advisory optimizer (simulation-based MPC).

Horizon      : from the current twin state to the end of the RH treatment.
Decisions    : x = [V_O2 (Nm3, future OB phase), t_deep (s, deep-vacuum duration),
                    argon (NL/min, all future vacuum phases)];  Al deoxidation is computed by
               the O-probe rule; chemical heating (Al+O2) by an energy balance if T is short
               and the plant has it enabled.
Discretization: phase-wise piecewise-constant inputs (the twin's native schedule form).
Method       : lexicographic.  Stage 1 - coarse grid search minimising the quality
               violation (feasibility first).  Stage 2 - scipy.optimize.minimize(COBYLA)
               on the economic objective with g_i(x) >= 0 constraints, warm-started from the
               best feasible grid point; maxiter and wall budget explicit.
Fallback     : deterministic - if COBYLA fails or exceeds budget, the best feasible grid point
               is returned; if no feasible point exists: status "NO_FEASIBLE_PLAN" with
               the least-violating plan and alternatives.
Sensitivity  : finite-difference (+/-5 %) of endpoint C, T, cost w.r.t. each decision at the
               optimum -> recommendation stability.
Simulations use a coarser but closure-checked solver setting (rtol 1e-4, max_step 30 s).
"""
from __future__ import annotations

import copy
import math
import time
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from ..schemas.configuration import Phase, SolverConfig
from ..services.reporting import evaluate_endpoint, rh_end_record
from .constraints import equipment_bounds, quality_constraints, violation
from .objectives import economic_cost

COARSE = dict(rtol=1e-5, max_step_s=20.0, record_interval_s=30.0)
VAC_STAGES = {"NATURAL_DECARB", "OB_DECARB", "DEEP_VACUUM", "DEOXIDATION", "CHEMICAL_HEATING", "ALLOYING",
              "HOMOGENIZATION", "FINAL_SAMPLING"}


def _retime(model, x: dict, ob_flow: float):
    """Modify FUTURE phases of a model copy according to decisions x; shift later events."""
    t_now = model.t
    table = model.phase_table
    shift = 0.0
    new = []
    for ph in table:  # modified IN PLACE (keeps the identity of the current phase dict)
        old_dur = ph["t_end"] - ph["t_start"]
        ph["t_start"] += shift
        ph["t_end"] += shift
        if ph["t_end"] > t_now + 1e-9:
            dur = old_dur
            if ph["stage"] == "OB_DECARB" and "V_O2_Nm3" in x:
                elapsed = max(t_now - ph["t_start"], 0.0)
                used = ph["oxygen_Nm3_h"] * elapsed / 3600.0
                rem = max(x["V_O2_Nm3"] - used, 0.0)
                flow = ph["oxygen_Nm3_h"] or ob_flow
                dur = elapsed + (rem / flow * 3600.0 if flow > 0 else 0.0)
                dur = max(dur, elapsed + 1.0)
            if ph["stage"] == "DEEP_VACUUM" and "t_deep_s" in x:
                elapsed = max(t_now - ph["t_start"], 0.0)
                dur = max(x["t_deep_s"], elapsed + 1.0)
            if "argon_NL_min" in x and ph["stage"] in VAC_STAGES:
                frac = 0.85 if ph["stage"] in ("HOMOGENIZATION", "FINAL_SAMPLING") else 1.0
                ph["argon_NL_min"] = x["argon_NL_min"] * frac
            if ph["stage"] == "DISPATCH":
                dur = 60.0  # optimizer evaluates RH end; dispatch cooling evaluated in verification run
            delta = dur - old_dur
            ph["t_end"] = ph["t_start"] + dur
            if abs(delta) > 1e-9:
                t_old_end = ph["t_end"] - delta
                for a in model.schedule.additions:
                    if a.t_s >= t_old_end - 1e-6 and a.t_s > t_now:
                        a.t_s += delta
                for s in model.schedule.samples:
                    if s.t_s >= t_old_end - 1e-6 and s.t_s > t_now:
                        s.t_s += delta
                shift += delta
        new.append(ph)
    # prev_o2 consistency
    for i in range(1, len(new)):
        new[i]["prev_o2"] = new[i - 1]["oxygen_Nm3_h"]
    model.phase_table = new
    model.t_end_schedule = new[-1]["t_end"]


def _add_chemical_heating(model, al_kg: float, o2_Nm3_h: float, dur_s: float):
    """Insert Al + O2 chemical heating into a model copy right after the DEOXIDATION phase."""
    from ..schemas.configuration import Addition
    table = model.phase_table
    idx = next((i for i, p in enumerate(table) if p["stage"] == "DEOXIDATION"), None)
    if idx is None or table[idx]["t_end"] <= model.t:
        return False
    base = dict(table[idx])
    t0 = base["t_end"]
    ch = dict(base)
    ch.update({"stage": "CHEMICAL_HEATING", "t_start": t0, "t_end": t0 + dur_s, "oxygen_Nm3_h": o2_Nm3_h,
               "oxygen_ramp_s": 15.0, "index": base["index"] + 0.5, "prev_o2": 0.0, "blocked": False, "block_reason": None,
               "note": "optimizer: chemical heating"})
    for p in table[idx + 1:]:
        p["t_start"] += dur_s
        p["t_end"] += dur_s
    for a in model.schedule.additions:
        if a.t_s >= t0 and a.t_s > model.t:
            a.t_s += dur_s
    for s in model.schedule.samples:
        if s.t_s >= t0 and s.t_s > model.t:
            s.t_s += dur_s
    model.phase_table = table[: idx + 1] + [ch] + table[idx + 1:]
    model.t_end_schedule = model.phase_table[-1]["t_end"]
    model.schedule.additions.append(Addition(t_s=t0 + 2, material="Al_shot", mass_kg=round(al_kg, 1), purpose="chemical heating"))
    model.schedule.additions.sort(key=lambda a: a.t_s)
    return True


class AdvisoryOptimizer:
    def __init__(self, base_model, plant, grade, budget_s: float = 240.0, max_iter: int = 8, progress=None):
        self.base = copy.deepcopy(base_model)  # snapshot: the live session may keep stepping
        self.base.guard = base_model.guard
        self.plant = plant
        self.grade = grade
        self.budget = budget_s
        self.max_iter = max_iter
        self.evals = []
        self.t0 = time.time()
        self.progress = progress or (lambda *_: None)
        self.has_ob = (plant.variant.value == "RH_OB" and plant.geometry.oxygen_tuyere_count > 0 and
                       plant.limits.oxygen_safety_prerequisites_confirmed and getattr(grade, "rh_ob_suitable", True) and
                       any(p["stage"] == "OB_DECARB" and p["t_end"] > base_model.t for p in base_model.phase_table))
        self.ob_flow = max([p["oxygen_Nm3_h"] for p in base_model.phase_table if p["stage"] == "OB_DECARB"] + [0.0]) or \
            min(1800.0, plant.limits.oxygen_max_Nm3_h)

    def _copy(self):
        m = copy.deepcopy(self.base)
        m.guard = self.base.guard
        m.scfg = m.scfg.model_copy(update=COARSE)
        m.records = m.records[-1:]
        return m

    def simulate(self, x: dict, chem: Optional[tuple] = None, full=False) -> dict:
        m = copy.deepcopy(self.base) if full else self._copy()
        m.guard = self.base.guard
        if not full:
            m.scfg = m.scfg.model_copy(update=COARSE)
        _retime(m, x, self.ob_flow)
        if full:
            # restore dispatch duration for the verification run
            for p in m.phase_table:
                if p["stage"] == "DISPATCH":
                    p["t_end"] = p["t_start"] + (self.grade.transfer_to_caster_s if self.grade else 900.0)
            m.t_end_schedule = m.phase_table[-1]["t_end"]
        if chem:
            _add_chemical_heating(m, *chem)
        m.step_to(m.t_end_schedule)
        g = quality_constraints(m.records, self.grade, self.plant)
        cost = economic_cost(m.records, self.plant, self.grade, m.applied_additions)
        e = rh_end_record(m.records)
        out = {"x": dict(x), "chem": chem, "g": g, "violation": violation(g), "cost": cost["total"], "cost_terms": cost,
               "end": {k: e.get(k) for k in ("t_s", "C_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm", "O_bulk_ppm", "T_bulk_K", "Al_bulk_ppm")},
               "status": m.status, "closure_ok": m.closure.ok, "blocked": [p["stage"] for p in m.phase_table if p.get("blocked")]}
        if m.status == "failed" or not m.closure.ok:
            out["violation"] += 10.0
        self.evals.append(out)
        if full:
            out["model"] = m
        return out

    def _budget_left(self):
        return self.budget - (time.time() - self.t0)

    def run(self) -> dict:
        lim = self.plant.limits
        b = equipment_bounds(self.plant, self.has_ob)
        cur = {p["stage"]: p for p in self.base.phase_table}
        ar0 = max([p["argon_NL_min"] for p in self.base.phase_table if p["stage"] == "DEEP_VACUUM"] + [lim.argon_min_NL_min])
        deep0 = (cur["DEEP_VACUUM"]["t_end"] - cur["DEEP_VACUUM"]["t_start"]) if "DEEP_VACUUM" in cur else 600.0
        ob0 = (cur["OB_DECARB"]["oxygen_Nm3_h"] * (cur["OB_DECARB"]["t_end"] - cur["OB_DECARB"]["t_start"]) / 3600.0) if "OB_DECARB" in cur else 0.0
        if "DEEP_VACUUM" in cur and cur["DEEP_VACUUM"]["t_end"] <= self.base.t:
            return {"status": "NOT_APPLICABLE", "message": "deep-vacuum phase already completed; only trim advice applies",
                    "evaluations": []}
        self.progress(0.02, "baseline")
        x_base = {"t_deep_s": deep0, "argon_NL_min": ar0}
        if self.has_ob:
            x_base["V_O2_Nm3"] = ob0
        base = self.simulate(x_base)
        # ---------- stage 1: feasibility grid
        t_grid = sorted({max(b["t_deep_s"][0], deep0 * f) for f in (0.75, 1.3, 1.8)})
        o_grid = [None]
        if self.has_ob:
            o_grid = sorted({min(max(ob0 * f + a, 0.0), b["V_O2_Nm3"][1]) for f, a in ((0.7, 0), (1.4, 20.0))})
        ar_max = b["argon_NL_min"][1]
        grid = []
        for td in t_grid:
            for vo in o_grid:
                x = {"t_deep_s": td, "argon_NL_min": ar_max}
                if vo is not None:
                    x["V_O2_Nm3"] = vo
                grid.append(x)
        n = len(grid)
        for i, x in enumerate(grid):
            if self._budget_left() < 20:
                break
            self.simulate(x)
            self.progress(0.05 + 0.45 * (i + 1) / n, f"feasibility grid {i+1}/{n}")
        feas = [e for e in self.evals if e["violation"] <= 1e-9]
        best_feas = min(feas, key=lambda e: e["cost"]) if feas else None
        # ---------- stage 2: COBYLA on economics subject to g >= 0
        names = ["t_deep_s", "argon_NL_min"] + (["V_O2_Nm3"] if self.has_ob else [])
        lo = np.array([b[k][0] for k in names])
        hi = np.array([b[k][1] for k in names])
        scale = hi - lo
        start = best_feas["x"] if best_feas else min(self.evals, key=lambda e: e["violation"])["x"]
        z0 = (np.array([start[k] for k in names]) - lo) / scale
        cache = {}

        def ev(z):
            z = np.clip(z, 0, 1)
            key = tuple(np.round(z, 4))
            if key not in cache:
                if self._budget_left() < 15:
                    raise TimeoutError
                xx = dict(zip(names, lo + z * scale))
                cache[key] = self.simulate(xx)
            return cache[key]

        cobyla_msg = "skipped"
        if self._budget_left() > 30:
            cons = [{"type": "ineq", "fun": (lambda z, k=k: ev(z)["g"][k])} for k in ("C", "H", "T_min", "T_max", "time")]
            cons += [{"type": "ineq", "fun": (lambda z, i=i: z[i])} for i in range(len(names))]
            cons += [{"type": "ineq", "fun": (lambda z, i=i: 1 - z[i])} for i in range(len(names))]
            ref = max(abs(best_feas["cost"]) if best_feas else 1.0, 1.0)
            try:
                res = minimize(lambda z: ev(z)["cost"] / ref, z0, method="COBYLA", constraints=cons,
                               options={"maxiter": self.max_iter, "rhobeg": 0.15, "tol": 1e-3})
                cobyla_msg = str(res.message)
            except TimeoutError:
                cobyla_msg = "wall-time budget reached - deterministic fallback to best grid point"
            self.progress(0.8, "COBYLA done")
        feas = [e for e in self.evals if e["violation"] <= 1e-9]
        if feas:
            best = min(feas, key=lambda e: e["cost"])
            status = "FEASIBLE_PLAN"
        else:
            best = min(self.evals, key=lambda e: (e["violation"], e["cost"]))
            status = "NO_FEASIBLE_PLAN"
        # ---------- thermal correction by chemical heating (energy balance), verified
        chem = None
        if best["g"]["T_min"] < 0 and self.plant.chemical_heating_enabled and self.has_ob_hw() and self._budget_left() > 15:
            dT = -best["g"]["T_min"] * 10.0 + 3.0
            M = self.base.M0
            al = dT * M * 830.0 / (28.8e6 * 0.80)
            o2 = al / 26.982 * 0.75 * 0.022414 / 0.88
            dur = 180.0
            flow = min(o2 / dur * 3600.0, lim.oxygen_max_Nm3_h)
            dur = o2 / flow * 3600.0
            trial = self.simulate(best["x"], chem=(al, flow, dur))
            if trial["violation"] < best["violation"]:
                best = trial
                chem = (al, flow, dur)
                if trial["violation"] <= 1e-9:
                    status = "FEASIBLE_PLAN"
        # ---------- sensitivity (finite differences)
        sens = {}
        if self._budget_left() > 20:
            for k in names:
                h = 0.05 * max(abs(best["x"][k]), 0.05 * (b[k][1] - b[k][0]))
                xp = dict(best["x"])
                xp[k] = min(xp[k] + h, b[k][1])
                r = self.simulate(xp, chem=chem)
                d = xp[k] - best["x"][k]
                if d > 0:
                    sens[k] = {"step": d, "dC_ppm_per_unit": (r["end"]["C_bulk_ppm"] - best["end"]["C_bulk_ppm"]) / d,
                               "dT_K_per_unit": (r["end"]["T_bulk_K"] - best["end"]["T_bulk_K"]) / d,
                               "dcost_per_unit": (r["cost"] - best["cost"]) / d,
                               "still_feasible": r["violation"] <= 1e-9}
                if self._budget_left() < 20:
                    break
        self.progress(0.9, "verification run")
        verify = self.simulate(best["x"], chem=chem, full=True)
        vm = verify.pop("model")
        limiting = min(best["g"], key=best["g"].get)
        alternatives = []
        if status == "NO_FEASIBLE_PLAN":
            viol = {k: v for k, v in best["g"].items() if v < 0}
            if "C" in viol:
                alternatives.append("Extend permissible treatment time (caster sequence) or reduce incoming C at BOF/EAF tapping")
                if not self.has_ob:
                    alternatives.append("Oxygen blowing unavailable/not permitted - if hardware exists, validate RH-OB practice")
                else:
                    alternatives.append("Raise per-heat oxygen limit only after refractory/tuyere engineering review")
            if "T_min" in viol:
                alternatives.append("Correct temperature upstream (tapping T) - in-RH chemical heating not available/insufficient")
            if "H" in viol:
                alternatives.append("Extend degassing; check vacuum pump capacity and leak rate")
            if "time" in viol:
                alternatives.append("Re-sequence caster or divert heat to a less demanding grade")
        frontier = sorted([{"t_treat_min": e["end"]["t_s"] / 60.0, "cost": e["cost"], "C_end": e["end"]["C_bulk_ppm"],
                            "T_end": e["end"]["T_bulk_K"], "feasible": e["violation"] <= 1e-9} for e in self.evals],
                          key=lambda d: d["t_treat_min"])
        plan = {"decisions": best["x"], "chemical_heating": None if chem is None else
                {"Al_kg": chem[0], "O2_Nm3_h": chem[1], "duration_s": chem[2]},
                "phases": [{k: p[k] for k in ("stage", "t_start", "t_end", "pressure_setpoint_Pa", "pressure_setpoint_end_Pa",
                                               "argon_NL_min", "oxygen_Nm3_h")} for p in vm.phase_table],
                "additions": vm.applied_additions}
        return {"status": status, "limiting_constraint": limiting, "constraint_margins": best["g"],
                "baseline": {k: base[k] for k in ("x", "g", "violation", "cost", "end", "cost_terms")},
                "optimized": {k: best[k] for k in ("x", "g", "violation", "cost", "end", "cost_terms", "chem")},
                "verification": {k: verify[k] for k in ("end", "g", "violation", "cost", "status", "closure_ok", "blocked")},
                "verification_endpoint": evaluate_endpoint(vm.records, self.grade, self.plant),
                "verification_trajectory": [{k: r.get(k) for k in ("t_s", "C_bulk_ppm", "T_bulk_K", "H_bulk_ppm", "N_bulk_ppm",
                                                                    "O_bulk_ppm", "P_Pa", "oxygen_Nm3_h", "argon_NL_min", "stage")}
                                            for r in vm.records],
                "plan": plan, "sensitivity": sens, "frontier": frontier, "alternatives": alternatives,
                "n_evaluations": len(self.evals), "cobyla": cobyla_msg, "wall_time_s": time.time() - self.t0,
                "method": "lexicographic: grid feasibility -> COBYLA economics -> energy-balance chemical heating -> FD sensitivity",
                "approval_required": "Operator acknowledgement; Metallurgist approval for oxygen/chemical heating changes",
                "actuator_authority": {"oxygen": "manual L1 oxygen station" if self.has_ob_hw() else "NOT INSTALLED",
                                       "argon": "manual L1 gas station", "vacuum": "pump staging per L1 recipe",
                                       "alloys": "vacuum hopper (manual release)"},
                "solver_settings": COARSE}

    def has_ob_hw(self):
        return self.plant.variant.value == "RH_OB" and self.plant.geometry.oxygen_tuyere_count > 0 and \
            self.plant.limits.oxygen_safety_prerequisites_confirmed
