import time

from app.orchestration.scenarios import build_scenario
from app.physics.solver import RHOBModel


def test_heat_runtime_budget():
    req = build_scenario("S1_RH_BASELINE_O2_OFF")
    m = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade)
    t0 = time.time()
    m.run()
    dt = time.time() - t0
    print(f"\nBENCHMARK one 47-min heat (BDF, rtol 1e-6): {dt:.2f} s wall, {m.n_rhs} RHS evaluations, {m.L.size} states")
    assert dt < 60.0
