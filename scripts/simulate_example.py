"""Command-line example: run a synthetic scenario and print endpoint / KPIs; write a CSV.

    python scripts/simulate_example.py S2_RHOB_OXYGEN_ASSISTED --csv out.csv
"""
import argparse
import csv
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401
from app.orchestration.scenarios import SCENARIO_DESCRIPTIONS, build_scenario  # noqa: E402
from app.orchestration.state_machine import make_guard  # noqa: E402
from app.physics.solver import RHOBModel  # noqa: E402
from app.services.reporting import compute_kpis, evaluate_endpoint  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="S2_RHOB_OXYGEN_ASSISTED", choices=list(SCENARIO_DESCRIPTIONS))
    ap.add_argument("--csv")
    a = ap.parse_args()
    req = build_scenario(a.scenario)
    m = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade, guard=make_guard(req.plant, req.grade))
    m.run()
    ep = evaluate_endpoint(m.records, req.grade, req.plant)
    k = compute_kpis(m.records, req.plant, m.applied_additions, req.heat.steel_mass_t)
    print(f"{a.scenario}: {SCENARIO_DESCRIPTIONS[a.scenario]}\nstatus {m.status}; closure mass {m.closure.max_rel_mass:.1e}, energy {m.closure.max_rel_energy:.1e}")
    for c in ep["checks"]:
        print(f"  {c['target']:<22} {c['value']:>12.4f} {c['unit']:<4} [{c['min']} .. {c['max']}]  {'OK' if c['ok'] else 'NOT MET'}")
    print(f"feasible: {ep['feasible']}  reasons: {ep['infeasibility_reasons']}")
    print({kk: (round(v, 3) if isinstance(v, float) else v) for kk, v in k.items() if not isinstance(v, dict)})
    if a.csv:
        keys = [kk for kk, v in m.records[0].items() if not isinstance(v, (dict, list))]
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["# SYNTHETIC DATA - NOT VALIDATED FOR PLANT OPERATION"])
            w.writerow(keys)
            for r in m.records:
                w.writerow([r.get(kk) for kk in keys])
        print("wrote", a.csv)


if __name__ == "__main__":
    main()
