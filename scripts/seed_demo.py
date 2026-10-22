"""Seed a running backend with demonstration heats via the HTTP API (exercises the real contract).

    python scripts/seed_demo.py --api http://localhost:8000
"""
import argparse

import httpx

SCEN = ["S1_RH_BASELINE_O2_OFF", "S2_RHOB_OXYGEN_ASSISTED", "S3_TIGHT_ULC_ENDPOINT", "S4_HIGH_HYDROGEN",
        "S5_PUMP_UNDERPERFORMANCE_LEAK", "S6_ARGON_FAILURE_THERMAL_LOSS", "S7_INFEASIBLE_CAPACITY", "S8_CHEMICAL_HEATING"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.api, timeout=600)
    tok = c.post("/api/v1/auth/demo-login", json={"account": "engineer"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    for s in a.only or SCEN:
        r = c.post("/api/v1/simulations", json={"scenario": s, "run_to_end": True}, headers=h)
        r.raise_for_status()
        d = r.json()
        print(f"{s:<34} {d['simulation_id']}  status={d['status']}  feasible={d['endpoint_current_trajectory'].get('feasible')}")


if __name__ == "__main__":
    main()
