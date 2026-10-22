import pytest
from pydantic import ValidationError

from app.orchestration.scenarios import build_scenario, grade_by_id, standard_schedule
from app.orchestration.state_machine import make_guard, validate_schedule
from app.physics.solver import RHOBModel
from app.schemas.configuration import HeatInput, Phase, PlantConfig, Schedule, SolverConfig


def test_conflicting_commands_rejected():
    plant = PlantConfig()
    s = Schedule(phases=[Phase(stage="IMMERSION", duration_s=30, vacuum_pump_on=True, vent=True)])
    msgs = [i.message for i in validate_schedule(s, plant) if i.severity == "error"]
    assert any("conflicting" in m for m in msgs)


def test_bad_transition_and_o2_outside_ob():
    plant = PlantConfig()
    s = Schedule(phases=[Phase(stage="IMMERSION", duration_s=30), Phase(stage="DEOXIDATION", duration_s=60, oxygen_Nm3_h=500)])
    msgs = [i.message for i in validate_schedule(s, plant)]
    assert any("not permitted" in m for m in msgs) and any("oxygen requested" in m for m in msgs)


def test_ktb_variant_rejected_and_rh_has_no_tuyeres():
    with pytest.raises(ValidationError):
        PlantConfig(variant="RH_KTB")
    assert PlantConfig(variant="RH").geometry.oxygen_tuyere_count == 0


def test_oxygen_never_started_without_prerequisites():
    req = build_scenario("S2_RHOB_OXYGEN_ASSISTED")
    req.plant.limits.oxygen_safety_prerequisites_confirmed = False
    m = RHOBModel(req.plant, req.heat, req.schedule, SolverConfig(record_interval_s=30), req.grade, guard=make_guard(req.plant, req.grade))
    m.step_to(700)
    assert max(r["oxygen_Nm3_h"] for r in m.records) == 0.0
    assert any("O2_SAFETY_PREREQ_UNKNOWN" in e["message"] for e in m.events)


def test_grade_forbids_ob():
    plant = PlantConfig()
    grade = grade_by_id("LOW-H-PLATE")
    heat = HeatInput(heat_id="T", grade_id="LOW-H-PLATE")
    sched = standard_schedule(plant, heat, grade, ob_Nm3_h=1000, ob_duration_s=60)
    m = RHOBModel(plant, heat, sched, SolverConfig(record_interval_s=30), grade, guard=make_guard(plant, grade))
    m.step_to(500)
    assert any("GRADE_NOT_RHOB_SUITABLE" in e["message"] for e in m.events)


def test_pause_freezes_clock():
    from app.orchestration.simulation_runner import SimulationSession
    from app.core.errors import Conflict
    s = SimulationSession(build_scenario("S1_RH_BASELINE_O2_OFF"))
    s.step(dt_s=120)
    s.pause()
    t = s.t
    with pytest.raises(Conflict):
        s.step(dt_s=60)
    assert s.t == t
    s.resume()
    s.step(dt_s=60)
    assert s.t == pytest.approx(t + 60)
    s.reset()
    assert s.t == 0.0
