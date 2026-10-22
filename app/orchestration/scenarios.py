"""Schedule templates and the reproducible SYNTHETIC demonstration scenarios.

All scenario data are ILLUSTRATIVE (not plant calibrated). Every scenario carries a fixed
seed so results are deterministic.
"""
from __future__ import annotations

from typing import Optional

from ..core.config import load_grades
from ..schemas.configuration import (Addition, GradeCard, HeatInput, Phase, PlantConfig, SampleRequest, Schedule,
                                     SimulationRequest, SolverConfig)


def estimate_deox_al_kg(heat: HeatInput, grade: Optional[GradeCard], ob_Nm3: float, extra_o_ppm: float = 0.0) -> float:
    M = heat.steel_mass_t * 1000
    c0 = heat.composition_ppm.get("C", 0.0)
    o0 = heat.composition_ppm.get("O", 0.0)
    c_end = (grade.C_max_ppm if grade else 30.0) * 0.6
    o_from_ob = ob_Nm3 * 1.429 * 0.85 / M * 1e6
    o_end = max(o0 + o_from_ob - (15.999 / 12.011) * max(c0 - c_end, 0) + extra_o_ppm, 150.0)
    al_target = 0.5 * ((grade.Al_min_wtpct if grade else 0.03) + (grade.Al_max_wtpct if grade else 0.06)) * 1e4  # ppm
    al_needed = o_end * 1e-6 * M * (2 * 26.982) / (3 * 15.999) + al_target * 1e-6 * M
    return round(al_needed / 0.92 / 5.0) * 5.0


def standard_schedule(plant: PlantConfig, heat: HeatInput, grade: Optional[GradeCard], *, ob_Nm3_h: float = 0.0,
                      ob_duration_s: float = 0.0, natural_s: float = 240.0, deep_s: float = 600.0,
                      argon_NL_min: Optional[float] = None, al_kg: Optional[float] = None,
                      chem_heat_al_kg: float = 0.0, chem_heat_o2_Nm3_h: float = 0.0, chem_heat_s: float = 0.0,
                      homog_s: float = 300.0, p_deep_Pa: float = 67.0, extra_alloys: Optional[list] = None,
                      lab_delay_s: float = 240.0, transfer_s: Optional[float] = None) -> Schedule:
    ar = argon_NL_min if argon_NL_min is not None else min(plant.limits.argon_max_NL_min,
                                                         max(plant.limits.argon_min_NL_min, 8.3 * heat.steel_mass_t))
    ph: list[Phase] = [
        Phase(stage="ARRIVAL_CHECKS", duration_s=60, snorkels_immersed=False, vacuum_pump_on=False,
              argon_NL_min=plant.limits.argon_min_NL_min, note="heat receipt, temperature/sample"),
        Phase(stage="IMMERSION", duration_s=30, vacuum_pump_on=False, argon_NL_min=0.4 * ar, note="lift ladle, immerse snorkels"),
    ]
    if ob_Nm3_h > 0 and ob_duration_s > 0:
        ph += [Phase(stage="PUMP_DOWN", duration_s=150, pressure_setpoint_Pa=101325, pressure_setpoint_end_Pa=15000, argon_NL_min=0.7 * ar),
               Phase(stage="OB_DECARB", duration_s=ob_duration_s, pressure_setpoint_Pa=12000, pressure_setpoint_end_Pa=5000,
                     argon_NL_min=ar, oxygen_Nm3_h=ob_Nm3_h, oxygen_ramp_s=20, note="RH-OB oxygen-assisted decarburization"),
               Phase(stage="NATURAL_DECARB", duration_s=natural_s, pressure_setpoint_Pa=5000, pressure_setpoint_end_Pa=800, argon_NL_min=ar)]
    else:
        ph += [Phase(stage="PUMP_DOWN", duration_s=150, pressure_setpoint_Pa=101325, pressure_setpoint_end_Pa=15000, argon_NL_min=0.7 * ar),
               Phase(stage="NATURAL_DECARB", duration_s=natural_s, pressure_setpoint_Pa=15000, pressure_setpoint_end_Pa=1500, argon_NL_min=ar)]
    ph.append(Phase(stage="DEEP_VACUUM", duration_s=deep_s, pressure_setpoint_Pa=max(4 * p_deep_Pa, 200), pressure_setpoint_end_Pa=p_deep_Pa,
                    argon_NL_min=ar, note="ULC decarburization, H/N removal"))
    t_deox = sum(p.duration_s for p in ph)
    ph.append(Phase(stage="DEOXIDATION", duration_s=180, pressure_setpoint_Pa=max(p_deep_Pa, 100), argon_NL_min=ar, note="Al deoxidation"))
    if chem_heat_s > 0 and chem_heat_o2_Nm3_h > 0:
        ph.append(Phase(stage="CHEMICAL_HEATING", duration_s=chem_heat_s, pressure_setpoint_Pa=max(p_deep_Pa, 100), argon_NL_min=ar,
                        oxygen_Nm3_h=chem_heat_o2_Nm3_h, oxygen_ramp_s=15, note="Al + O2 reheating"))
    t_alloy = sum(p.duration_s for p in ph)
    ph.append(Phase(stage="ALLOYING", duration_s=180, pressure_setpoint_Pa=max(p_deep_Pa, 100), argon_NL_min=ar))
    ph.append(Phase(stage="HOMOGENIZATION", duration_s=homog_s, pressure_setpoint_Pa=max(p_deep_Pa, 100), argon_NL_min=0.85 * ar,
                    note="mixing and inclusion flotation"))
    t_final = sum(p.duration_s for p in ph)
    ph.append(Phase(stage="FINAL_SAMPLING", duration_s=120, pressure_setpoint_Pa=max(p_deep_Pa, 100), argon_NL_min=0.85 * ar))
    ph.append(Phase(stage="VACUUM_BREAK", duration_s=60, pressure_setpoint_Pa=101325, vacuum_pump_on=False, vent=True,
                    argon_NL_min=0.4 * ar))
    ph.append(Phase(stage="DISPATCH", duration_s=transfer_s if transfer_s is not None else (grade.transfer_to_caster_s if grade else 900),
                    snorkels_immersed=False, vacuum_pump_on=False, argon_NL_min=0.0, note="ladle to caster (covered)"))
    ob_total = ob_Nm3_h * ob_duration_s / 3600.0
    adds = []
    al = al_kg if al_kg is not None else estimate_deox_al_kg(heat, grade, ob_total)
    al_target = 0.5 * ((grade.Al_min_wtpct if grade else 0.03) + (grade.Al_max_wtpct if grade else 0.06)) * 1e4
    if al > 0:
        adds.append(Addition(t_s=t_deox + 5, material="Al_shot", mass_kg=al, purpose="deoxidation",
                             auto_target_Al_ppm=None if al_kg is not None else al_target + (chem_heat_al_kg > 0) * 0))
    if chem_heat_al_kg > 0:
        adds.append(Addition(t_s=t_deox + 180 + 2, material="Al_shot", mass_kg=chem_heat_al_kg, purpose="chemical heating"))
    M = heat.steel_mass_t * 1000
    if grade is not None and grade.Ti_min_wtpct:
        ti_t = 0.5 * (grade.Ti_min_wtpct + (grade.Ti_max_wtpct or grade.Ti_min_wtpct)) / 100 * M
        adds.append(Addition(t_s=t_alloy + 10, material="FeTi70", mass_kg=round(ti_t / (0.70 * 0.80) / 5) * 5, purpose="Ti alloying"))
    if grade is not None and grade.Mn_min_wtpct:
        mn_now = heat.composition_ppm.get("Mn", 0) * 1e-4
        if mn_now < grade.Mn_min_wtpct:
            need = (0.5 * (grade.Mn_min_wtpct + (grade.Mn_max_wtpct or grade.Mn_min_wtpct)) - mn_now) / 100 * M
            adds.append(Addition(t_s=t_alloy + 30, material="LC_FeMn", mass_kg=round(need / (0.8 * 0.95) / 5) * 5, purpose="Mn trim"))
    if grade is not None and grade.family == "ELECTRICAL":
        need = 1.2 / 100 * M
        adds.append(Addition(t_s=t_alloy + 20, material="FeSi75", mass_kg=round(need / (0.75 * 0.9) / 10) * 10, purpose="Si alloying"))
    for a in extra_alloys or []:
        adds.append(a)
    samples = [SampleRequest(t_s=30, kinds=["C", "O", "H", "N", "Mn", "T"], lab_delay_s=lab_delay_s),
               SampleRequest(t_s=t_deox - 2, kinds=["C", "O", "H", "N", "T"], lab_delay_s=lab_delay_s),
               SampleRequest(t_s=t_final + 5, kinds=["C", "O", "H", "N", "Al", "Ti", "Mn", "Si", "T"], lab_delay_s=lab_delay_s)]
    return Schedule(phases=ph, additions=sorted(adds, key=lambda a: a.t_s), samples=samples)


def grade_by_id(grade_id: str) -> Optional[GradeCard]:
    for g in load_grades():
        if g.grade_id == grade_id:
            return g
    return None


SCENARIO_DESCRIPTIONS = {
    "S1_RH_BASELINE_O2_OFF": "Standard conventional RH baseline, oxygen OFF (variant RH).",
    "S2_RHOB_OXYGEN_ASSISTED": "RH-OB oxygen-assisted decarburization of a high-C / low-O heat, oxygen ON within limits.",
    "S3_TIGHT_ULC_ENDPOINT": "Tight ULC carbon endpoint (IF grade) with oxygen balance top-up and long deep vacuum.",
    "S4_HIGH_HYDROGEN": "High hydrogen ingress, longer degassing requirement (low-H plate, oxygen forbidden).",
    "S5_PUMP_UNDERPERFORMANCE_LEAK": "Pump underperformance + air leakage: poor vacuum, low-confidence advisory.",
    "S6_ARGON_FAILURE_THERMAL_LOSS": "Lift-nozzle fouling (argon failure) + cold ladle: elevated thermal loss.",
    "S7_INFEASIBLE_CAPACITY": "Insufficient oxygen/pressure capacity for a very high-C heat in the time window: infeasibility.",
    "S8_CHEMICAL_HEATING": "RH-OB Al + O2 chemical reheating of a cold heat (only because enabled in demo config).",
}


def build_scenario(name: str) -> SimulationRequest:
    plant = PlantConfig()
    heat = HeatInput()
    grade = grade_by_id("ULC-DRAWING")
    kw = {}
    seed = 1000 + list(SCENARIO_DESCRIPTIONS).index(name)
    if name == "S1_RH_BASELINE_O2_OFF":
        plant = PlantConfig(variant="RH")
        heat = HeatInput(heat_id="SYN-S1", grade_id="ULC-DRAWING", composition_ppm={**HeatInput().composition_ppm, "C": 350, "O": 650})
    elif name == "S2_RHOB_OXYGEN_ASSISTED":
        heat = HeatInput(heat_id="SYN-S2", grade_id="ULC-DRAWING", T_arrival_K=1888,
                         composition_ppm={**HeatInput().composition_ppm, "C": 520, "O": 380})
        kw = dict(ob_Nm3_h=2000, ob_duration_s=300, natural_s=180)
    elif name == "S3_TIGHT_ULC_ENDPOINT":
        grade = grade_by_id("IF-ULC")
        heat = HeatInput(heat_id="SYN-S3", grade_id="IF-ULC", T_arrival_K=1896,
                         composition_ppm={**HeatInput().composition_ppm, "C": 420, "O": 520})
        kw = dict(ob_Nm3_h=1200, ob_duration_s=120, natural_s=180, deep_s=780, p_deep_Pa=67)
    elif name == "S4_HIGH_HYDROGEN":
        grade = grade_by_id("LOW-H-PLATE")
        plant = PlantConfig(variant="RH")
        heat = HeatInput(heat_id="SYN-S4", grade_id="LOW-H-PLATE", T_arrival_K=1885,
                         composition_ppm={**HeatInput().composition_ppm, "C": 1500, "O": 35, "H": 9.0, "N": 55, "Al": 300,
                                          "Si": 2500, "Mn": 13000})
        kw = dict(natural_s=120, deep_s=1020, al_kg=40, p_deep_Pa=67)
    elif name == "S5_PUMP_UNDERPERFORMANCE_LEAK":
        plant = PlantConfig()
        plant.vacuum.pump_health = 0.55
        plant.vacuum.air_leak_kg_h = 160.0
        heat = HeatInput(heat_id="SYN-S5", grade_id="ULC-DRAWING")
    elif name == "S6_ARGON_FAILURE_THERMAL_LOSS":
        plant = PlantConfig()
        plant.kinetics.lift_nozzle_fouling = 0.35
        plant.thermal.ladle_hot_face_initial_K = 1380.0
        plant.thermal.vessel_preheat_K = 1150.0
        heat = HeatInput(heat_id="SYN-S6", grade_id="ULC-DRAWING", T_arrival_K=1885)
    elif name == "S7_INFEASIBLE_CAPACITY":
        plant = PlantConfig()
        plant.vacuum.pump_health = 0.75
        plant.limits.oxygen_max_total_Nm3 = 100.0
        grade = grade_by_id("IF-ULC")
        heat = HeatInput(heat_id="SYN-S7", grade_id="IF-ULC", T_arrival_K=1880,
                         composition_ppm={**HeatInput().composition_ppm, "C": 800, "O": 300})
        kw = dict(ob_Nm3_h=1800, ob_duration_s=240, natural_s=120, deep_s=420)
    elif name == "S8_CHEMICAL_HEATING":
        heat = HeatInput(heat_id="SYN-S8", grade_id="ULC-DRAWING", T_arrival_K=1868)
        kw = dict(chem_heat_al_kg=170, chem_heat_o2_Nm3_h=2500, chem_heat_s=180)
    else:
        raise KeyError(name)
    sched = standard_schedule(plant, heat, grade, **kw)
    if name == "S8_CHEMICAL_HEATING":
        # chemical heating consumes O2 with the extra Al: keep deox Al and the heating Al separate
        pass
    return SimulationRequest(plant=plant, heat=heat, grade=grade, schedule=sched, scenario_name=name,
                             scenario_id=name, solver=SolverConfig(seed=seed))
