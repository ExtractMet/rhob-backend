import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / 'test_rhob.db'}")

import pytest  # noqa: E402

import app  # noqa: E402,F401
from app.data.db import init_db  # noqa: E402

init_db()


@pytest.fixture(scope="session")
def runs():
    """Run a few synthetic scenarios once per test session (shared, deterministic)."""
    from app.orchestration.scenarios import build_scenario
    from app.orchestration.state_machine import make_guard
    from app.physics.solver import RHOBModel
    out = {}
    for name in ["S1_RH_BASELINE_O2_OFF", "S2_RHOB_OXYGEN_ASSISTED", "S7_INFEASIBLE_CAPACITY"]:
        req = build_scenario(name)
        m = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade, guard=make_guard(req.plant, req.grade))
        m.run()
        out[name] = (req, m)
    return out
