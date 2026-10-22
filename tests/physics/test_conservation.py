"""Conservation, closure, O2-ON vs O2-OFF divergence, robustness scenarios."""
import copy

import numpy as np
import pytest

from app.orchestration.scenarios import build_scenario, standard_schedule, grade_by_id
from app.orchestration.state_machine import make_guard
from app.physics.solver import RHOBModel
from app.schemas.configuration import HeatInput, PlantConfig, SolverConfig
from app.services.reporting import evaluate_endpoint, rh_end_record

FAST = SolverConfig(rtol=1e-6, max_step_s=10, record_interval_s=30)


def run(plant, heat, grade=None, sched=None, **kw):
    grade = grade or grade_by_id(heat.grade_id)
    sched = sched or standard_schedule(plant, heat, grade, **kw)
    m = RHOBModel(plant, heat, sched, FAST, grade, guard=make_guard(plant, grade))
    m.run()
    return m


def test_closure_baseline_and_ob(runs):
    for name in ["S1_RH_BASELINE_O2_OFF", "S2_RHOB_OXYGEN_ASSISTED"]:
        req, m = runs[name]
        assert m.status == "completed", name
        assert m.closure.max_rel_mass < 1e-8, (name, m.closure.message())
        assert m.closure.max_rel_energy < 1e-8, (name, m.closure.message())
        for rec in m.records:
            assert abs(rec["argon_balance_residual_mol"]) < 1e-3


def test_every_element_closes(runs):
    req, m = runs["S2_RHOB_OXYGEN_ASSISTED"]
    res = m.records[-1]["element_residual_kg"]
    for el, r in res.items():
        assert abs(r) < 1e-5, (el, r)


def test_o2_on_differs_from_o2_off(runs):
    _, m1 = runs["S1_RH_BASELINE_O2_OFF"]
    _, m2 = runs["S2_RHOB_OXYGEN_ASSISTED"]
    e2 = rh_end_record(m2.records)
    assert e2["cum_dC_jet_kg"] > 1.0 and rh_end_record(m1.records)["cum_dC_jet_kg"] == 0.0
    assert max(r["oxygen_Nm3_h"] for r in m2.records) > 0 and max(r["oxygen_Nm3_h"] for r in m1.records) == 0
    ob = [r for r in m2.records if r["stage"] == "OB_DECARB"]
    assert max(r["Q_rxn_O2_to_O_W"] for r in ob) > 1e6  # exothermic O2 dissolution only when blowing


def test_no_negative_inventories(runs):
    for name, (_, m) in runs.items():
        assert not any("negative inventory" in w for w in m.warnings), (name, m.warnings)
        for r in m.records:
            for k in ("C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm"):
                assert r[k] >= -1e-6


def test_infeasibility_declared(runs):
    req, m = runs["S7_INFEASIBLE_CAPACITY"]
    ep = evaluate_endpoint(m.records, req.grade, req.plant)
    assert not ep["feasible"]
    assert any(r["target"] == "C" and "oxygen" in r["why"] for r in ep["infeasibility_reasons"])
    assert any(e["kind"] == "TRANSITION_BLOCKED" and "O2_TOTAL_LIMIT" in e["message"] for e in m.events)


def test_pump_off_and_leak():
    plant = PlantConfig()
    plant.vacuum.pump_health = 0.0
    m = run(plant, HeatInput(heat_id="T-PUMPOFF"), transfer_s=60)
    assert min(r["P_Pa"] for r in m.records) > 90000  # no vacuum without pumps
    assert m.closure.ok
    plant2 = PlantConfig(); plant2.vacuum.air_leak_kg_h = 300
    m2 = run(plant2, HeatInput(heat_id="T-LEAK"), transfer_s=60)
    base = run(PlantConfig(), HeatInput(heat_id="T-BASE"), transfer_s=60)
    assert min(r["P_Pa"] for r in m2.records) > min(r["P_Pa"] for r in base.records)
    assert rh_end_record(m2.records)["N_bulk_ppm"] > rh_end_record(base.records)["N_bulk_ppm"]


def test_argon_failure_stagnant_and_o2_blocked():
    plant = PlantConfig(); plant.kinetics.lift_nozzle_fouling = 0.0
    heat = HeatInput(heat_id="T-ARFAIL", composition_ppm={**HeatInput().composition_ppm, "C": 500, "O": 380})
    m = run(plant, heat, ob_Nm3_h=1500, ob_duration_s=120, transfer_s=60)
    assert max(r["q_circ_t_min"] for r in m.records) == 0.0
    assert any("NO_CIRCULATION" in e["message"] or "O2_VESSEL_DEPTH_LOW" in e["message"] for e in m.events if e["kind"] == "TRANSITION_BLOCKED")
    assert m.closure.ok


def test_zero_alloy_and_reheating_off():
    plant = PlantConfig(chemical_heating_enabled=False)
    heat = HeatInput(heat_id="T-NOALLOY")
    grade = grade_by_id("ULC-DRAWING")
    sched = standard_schedule(plant, heat, grade, al_kg=0.0, chem_heat_al_kg=150, chem_heat_o2_Nm3_h=2000, chem_heat_s=120, transfer_s=60)
    m = RHOBModel(plant, heat, sched, FAST, grade, guard=make_guard(plant, grade))
    m.run()
    assert any("CHEM_HEATING_DISABLED" in e["message"] for e in m.events)
    assert m.closure.ok


def test_very_low_concentrations_converge():
    comp = {**HeatInput().composition_ppm, "C": 5.0, "O": 3.0, "H": 0.5, "N": 10.0, "Al": 450.0}
    m = run(PlantConfig(variant="RH"), HeatInput(heat_id="T-LOW", composition_ppm=comp), al_kg=0.0, transfer_s=60)
    assert m.status == "completed" and m.closure.ok
    assert all(r["C_bulk_ppm"] >= 0 and r["H_bulk_ppm"] >= 0 for r in m.records)


def test_extreme_sample_delay_and_abort():
    req = build_scenario("S1_RH_BASELINE_O2_OFF")
    req.schedule.samples[1].lab_delay_s = 3600
    req.schedule.abort_at_s = 700.0
    m = RHOBModel(req.plant, req.heat, req.schedule, FAST, req.grade, guard=make_guard(req.plant, req.grade))
    m.run()
    assert any(e["kind"] == "ABORT" for e in m.events)
    assert any(r["stage"] == "ABORT_VACUUM_BREAK" for r in m.records)
    assert m.status == "completed"
    assert any(e["kind"] == "ABORT_CANCELLED" for e in m.events)
    assert m.closure.ok


def test_reproducible_with_seed(runs):
    req, m = runs["S1_RH_BASELINE_O2_OFF"]
    m2 = RHOBModel(req.plant, req.heat, req.schedule, req.solver, req.grade, guard=make_guard(req.plant, req.grade))
    m2.run()
    assert m2.records[-1]["C_bulk_ppm"] == pytest.approx(m.records[-1]["C_bulk_ppm"], rel=1e-12)
