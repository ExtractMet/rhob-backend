"""Installation self-check: imports, thermodynamic sanity, a short closure-checked run."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401
from app.core.config import MODEL_VERSION  # noqa: E402
from app.orchestration.scenarios import build_scenario  # noqa: E402
from app.physics import thermodynamics as td  # noqa: E402
from app.physics.solver import RHOBModel  # noqa: E402


def main():
    print(f"rhob-backend {MODEL_VERSION} | python {sys.version.split()[0]}")
    m = td.co_equilibrium_product(1873.0, 101325.0, 1, 1)
    assert 0.0022 < m < 0.0026, m
    print(f"  thermo OK: [C][O] at 1 atm, 1873 K = {m:.5f}")
    req = build_scenario("S1_RH_BASELINE_O2_OFF")
    mdl = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade)
    t0 = time.time()
    mdl.step_to(900)
    print(f"  15-min run: {time.time()-t0:.1f} s, status {mdl.status}, C = {mdl.records[-1]['C_bulk_ppm']:.1f} ppm, "
          f"closure mass {mdl.closure.max_rel_mass:.1e} energy {mdl.closure.max_rel_energy:.1e}")
    assert mdl.closure.ok
    print("INSTALL CHECK PASSED")


if __name__ == "__main__":
    main()
