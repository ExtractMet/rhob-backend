"""Generate the SYNTHETIC heat dataset used to train/demonstrate the residual ML model.

Each heat = one nominal twin run + one 'plant' run that contains UNMODELLED plant effects
(snorkel-age circulation loss, ladle-idle thermal state) and random kinetic scatter. The
residual (plant - twin) at RH end is the ML target. Deterministic for a given seed.

Usage:  python scripts/generate_synthetic_heats.py --n 80 --seed 42
Writes: app/datasets/synthetic_heats.json, app/datasets/synthetic_heat_001.csv,
        app/datasets/synthetic_live_trace.csv
"""
from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.estimation.uncertainty import sample_kinetics  # noqa: E402
from app.orchestration.scenarios import build_scenario, grade_by_id, standard_schedule  # noqa: E402
from app.physics.solver import RHOBModel  # noqa: E402
from app.schemas.configuration import HeatInput, PlantConfig, SolverConfig  # noqa: E402
from app.services.reporting import rh_end_record  # noqa: E402

SOLVER = SolverConfig(rtol=1e-5, max_step_s=20, record_interval_s=30)


def one_heat(i: int, rng: np.random.Generator) -> dict:
    grade = grade_by_id("ULC-DRAWING")
    plant = PlantConfig()
    mass = float(rng.uniform(285, 315))
    C0 = float(rng.uniform(280, 600))
    O0 = float(rng.uniform(280, 720))
    T0 = float(rng.uniform(1878, 1905))
    H0 = float(rng.uniform(3.0, 8.0))
    N0 = float(rng.uniform(30, 50))
    comp = {**HeatInput().composition_ppm, "C": C0, "O": O0, "H": H0, "N": N0}
    heat = HeatInput(heat_id=f"SYN-ML-{i:03d}", grade_id=grade.grade_id, steel_mass_t=mass, T_arrival_K=T0, composition_ppm=comp)
    o_def = (15.999 / 12.011) * C0 + 180 - O0
    V = float(np.clip(o_def * 1e-6 * mass * 1000 / (1.429 * 0.85) * rng.uniform(0.7, 1.2), 0, 220)) if o_def > 0 else 0.0
    t_deep = float(rng.uniform(480, 900))
    ar = float(rng.uniform(1800, 3000))
    p_deep = float(rng.uniform(67, 150))
    leak = float(rng.uniform(5, 80))
    foul = float(rng.uniform(0.6, 1.0))
    age = float(rng.uniform(0, 120))
    idle = float(rng.uniform(10, 120))
    plant.vacuum.air_leak_kg_h = leak
    plant.kinetics.lift_nozzle_fouling = foul
    ob_flow = 1800.0
    sched = standard_schedule(plant, heat, grade, ob_Nm3_h=ob_flow if V > 5 else 0.0, ob_duration_s=V / ob_flow * 3600 if V > 5 else 0.0,
                              deep_s=t_deep, argon_NL_min=ar, p_deep_Pa=p_deep, transfer_s=60)
    twin = RHOBModel(plant, heat, sched, SOLVER, grade, label="twin")
    twin.run()
    # plant: unmodelled effects + kinetic scatter + assay error
    kin = sample_kinetics(plant.kinetics, rng)
    kin = {k: getattr(plant.kinetics, k) * (v / getattr(plant.kinetics, k)) ** 0.5 for k, v in kin.items()}
    kin["circulation_multiplier"] *= (1.0 - 0.0025 * age)
    p2 = plant.model_copy(deep=True)
    p2.thermal.ladle_hot_face_initial_K = 1700.0 - 2.5 * idle
    p2.thermal.ladle_shell_initial_K = 600.0 - 1.2 * idle
    heat_p = heat.model_copy(update={"composition_ppm": {**comp, "C": C0 * math.exp(rng.normal(0, 0.03)),
                                                         "O": O0 * math.exp(rng.normal(0, 0.05))},
                                     "T_arrival_K": T0 + float(rng.normal(0, 2.0))})
    plant_m = RHOBModel(p2, heat_p, sched, SOLVER, grade, kin_overrides=kin, label="plant")
    plant_m.run()
    et, ep = rh_end_record(twin.records), rh_end_record(plant_m.records)
    vac = [r for r in twin.records if r["stage"] == "DEEP_VACUUM"]
    K = float(np.mean([r["K_app_1_min"] for r in vac])) if vac else 0.0
    return {"heat_index": i, "heat_id": heat.heat_id, "C0_ppm": C0, "O0_ppm": O0, "T0_K": T0, "H0_ppm": H0, "N0_ppm": N0,
            "mass_t": mass, "V_O2_Nm3": V, "t_deep_s": t_deep, "argon_NL_min": ar, "P_deep_Pa": p_deep, "leak_kg_h": leak,
            "fouling": foul, "snorkel_age_heats": age, "ladle_idle_min": idle, "twin_C_end_ppm": et["C_bulk_ppm"],
            "twin_T_end_K": et["T_bulk_K"], "twin_Kapp_1_min": K, "plant_C_end_ppm": ep["C_bulk_ppm"], "plant_T_end_K": ep["T_bulk_K"],
            "resid_lnC": math.log(max(ep["C_bulk_ppm"], 0.1) / max(et["C_bulk_ppm"], 0.1)), "resid_T_K": ep["T_bulk_K"] - et["T_bulk_K"],
            "twin_closure_ok": twin.closure.ok, "plant_closure_ok": plant_m.closure.ok, "provenance": "SYNTHETIC"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-heats", action="store_true", help="only write the scenario CSV traces")
    a = ap.parse_args()
    out = ROOT / "app" / "datasets"
    out.mkdir(parents=True, exist_ok=True)
    # 1) scenario trace CSV (believable staged chemistry/vacuum/argon/oxygen/lab data)
    req = build_scenario("S2_RHOB_OXYGEN_ASSISTED")
    m = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade, label="twin")
    m.run()
    cols = ["t_s", "stage", "P_Pa", "P_sp_Pa", "argon_NL_min", "oxygen_Nm3_h", "T_bulk_K", "C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm",
            "N_bulk_ppm", "Al_bulk_ppm", "Ti_bulk_ppm", "q_circ_t_min", "offgas_CO_Nm3_h", "offgas_CO2_Nm3_h", "offgas_Ar_Nm3_h",
            "x_CO", "total_O_ppm", "mass_balance_relative_error", "energy_balance_relative_error"]
    with open(out / "synthetic_heat_001.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# SYNTHETIC DATA - ENGINEERING DEMONSTRATION - NOT VALIDATED FOR PLANT OPERATION"])
        w.writerow(cols)
        for r in m.records:
            w.writerow([r.get(c) for c in cols])
    rng = np.random.default_rng(a.seed)
    live_cols = ["t_s", "tag", "value", "unit", "quality", "source"]
    with open(out / "synthetic_live_trace.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# SYNTHETIC live signal trace (noisy measurements of a twin run) - illustrative"])
        w.writerow(live_cols)
        for r in m.records[::3]:
            w.writerow([r["t_s"], "RH1.VAC.PT101", round(r["P_Pa"] * (1 + rng.normal(0, 0.01)), 1), "Pa_abs", "GOOD", "synthetic"])
            w.writerow([r["t_s"], "RH1.AR.FT201", round(r["argon_NL_min"] * (1 + rng.normal(0, 0.01)), 1), "NL/min", "GOOD", "synthetic"])
            w.writerow([r["t_s"], "RH1.O2.FT301", round(r["oxygen_Nm3_h"] * (1 + rng.normal(0, 0.01)), 1), "Nm3/h", "GOOD", "synthetic"])
            w.writerow([r["t_s"], "RH1.OG.AT401_CO", round(max(r["x_CO"] * 100 * (1 + rng.normal(0, 0.03)), 0), 2), "vol% dry", "GOOD", "synthetic"])
    if a.skip_heats:
        return
    heats = []
    t0 = time.time()
    for i in range(a.n):
        heats.append(one_heat(i, rng))
        print(f"heat {i+1}/{a.n}  {time.time()-t0:.0f}s  resid_lnC={heats[-1]['resid_lnC']:+.3f} resid_T={heats[-1]['resid_T_K']:+.2f}", flush=True)
    with open(out / "synthetic_heats.json", "w") as f:
        json.dump({"banner": "SYNTHETIC DATA - NOT PLANT DATA", "seed": a.seed, "generator": "scripts/generate_synthetic_heats.py",
                   "heats": heats}, f, indent=1)


if __name__ == "__main__":
    main()
