import math

import pytest

from app.orchestration.scenarios import build_scenario
from app.orchestration.simulation_runner import SimulationSession


@pytest.fixture(scope="module")
def session():
    s = SimulationSession(build_scenario("S2_RHOB_OXYGEN_ASSISTED"))
    s.run_to_end()
    return s


def test_ekf_tracks_synthetic_plant(session):
    e = session.estimator()
    truth = {r["t_s"]: r["C_ppm"] for r in e["plant_truth"]}
    end = [q for q in e["trace"] if 1400 < q["t_s"] < 2000]
    errs = [abs(q["C_ppm"] - truth[q["t_s"]]) for q in end if q["t_s"] in truth]
    assert errs and max(errs) < 8.0
    for l in e["log"]:
        assert abs(l["post_bias_ppm"]) <= abs(l["pre_bias_ppm"]) + 1e-9


def test_lab_assimilation_changes_forecast(session):
    s = SimulationSession(build_scenario("S1_RH_BASELINE_O2_OFF"))
    s.step(to_s=1400)
    lr = [l for l in s.available_lab_results() if l["available"]][-1]
    rec = s.apply_lab_result({"C_ppm": lr["values"]["C_ppm"] * 1.5}, lr["t_sample_s"])
    assert rec["forecast_after"]["rh_end_state"]["C_bulk_ppm"] != pytest.approx(rec["forecast_before"]["rh_end_state"]["C_bulk_ppm"], rel=1e-3)
    assert s.twin.closure.ok  # correction booked explicitly, closure stays exact
    assert s.twin.closure.corrections


def test_ml_validation_gate_and_projection():
    from app.ml.training import get_model, load_dataset
    m, rep = get_model()
    assert rep["split"]["train"] > rep["split"]["test"] > 0
    for v in rep["targets"].values():
        assert "validation_gate" in v
    row = load_dataset()[0]
    p = m.predict(row)
    assert p["C_corrected_ppm"] >= 0.5 and abs(p["T_corrected_K"] - p["physics_T_K"]) <= 25.0 + 1e-9
