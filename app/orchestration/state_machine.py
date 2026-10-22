"""Configurable RH-OB process-state machine with guarded transitions.

Stage order is plant-configurable via ALLOWED_TRANSITIONS; a schedule is validated against
it before any run. Guards are evaluated at phase entry against the CURRENT model state.
A failed guard never issues a conflicting command: the phase runs with oxygen OFF (the only
manipulated variable whose guard can fail here), and a TRANSITION_BLOCKED event with a
traceable reason code is logged. Safety interlocks belong to the plant DCS/PLC; in this
demo they are SIMULATED read-only indicators (limits.oxygen_safety_prerequisites_confirmed).
"""
from __future__ import annotations

from dataclasses import dataclass

STAGES = {
    "ARRIVAL_CHECKS": "Heat identification, receipt and laboratory reconciliation",
    "IMMERSION": "Ladle positioning, lift and snorkel immersion checks",
    "PUMP_DOWN": "Pump-down / vacuum establishment and argon lift initiation",
    "NATURAL_DECARB": "Natural (vacuum) decarburization / pre-degassing",
    "OB_DECARB": "Oxygen-assisted decarburization (RH-OB phase)",
    "DEEP_VACUUM": "Deep-vacuum holding: C/H/N removal",
    "DEOXIDATION": "Oxygen stop, Al deoxidation",
    "CHEMICAL_HEATING": "Al + O2 chemical reheating (only where enabled & validated)",
    "ALLOYING": "Alloy additions and trimming",
    "HOMOGENIZATION": "Homogenization and inclusion flotation holding",
    "FINAL_SAMPLING": "Final sampling, temperature/chemistry trimming",
    "VACUUM_BREAK": "Controlled vacuum break",
    "ABORT_VACUUM_BREAK": "Abort path: oxygen off, vacuum break",
    "DISPATCH": "Snorkel withdrawal, dispatch to caster",
}

ALLOWED_TRANSITIONS = {
    None: {"ARRIVAL_CHECKS", "IMMERSION"},
    "ARRIVAL_CHECKS": {"IMMERSION"},
    "IMMERSION": {"PUMP_DOWN"},
    "PUMP_DOWN": {"NATURAL_DECARB", "OB_DECARB", "DEEP_VACUUM"},
    "NATURAL_DECARB": {"NATURAL_DECARB", "OB_DECARB", "DEEP_VACUUM", "DEOXIDATION"},
    "OB_DECARB": {"OB_DECARB", "NATURAL_DECARB", "DEEP_VACUUM"},
    "DEEP_VACUUM": {"DEEP_VACUUM", "DEOXIDATION", "OB_DECARB", "VACUUM_BREAK"},
    "DEOXIDATION": {"CHEMICAL_HEATING", "ALLOYING", "HOMOGENIZATION", "FINAL_SAMPLING"},
    "CHEMICAL_HEATING": {"ALLOYING", "HOMOGENIZATION"},
    "ALLOYING": {"ALLOYING", "HOMOGENIZATION", "FINAL_SAMPLING", "CHEMICAL_HEATING"},
    "HOMOGENIZATION": {"HOMOGENIZATION", "FINAL_SAMPLING", "ALLOYING", "VACUUM_BREAK"},
    "FINAL_SAMPLING": {"ALLOYING", "HOMOGENIZATION", "VACUUM_BREAK"},
    "VACUUM_BREAK": {"DISPATCH"},
    "ABORT_VACUUM_BREAK": {"DISPATCH"},
    "DISPATCH": set(),
}

ROLE_FOR_TRANSITION = {"OB_DECARB": "Operator", "CHEMICAL_HEATING": "Metallurgist", "ABORT_VACUUM_BREAK": "Operator"}

REASON_CODES = {
    "O2_NOT_INSTALLED": "Equipment variant has no oxygen tuyeres",
    "O2_SAFETY_PREREQ_UNKNOWN": "Oxygen safety prerequisites not confirmed by plant interlocks",
    "O2_VESSEL_DEPTH_LOW": "Vessel bath depth above tuyeres below configured minimum",
    "O2_PRESSURE_HIGH": "Vessel pressure above oxygen permissive limit",
    "O2_FLOW_LIMIT": "Requested oxygen flow exceeds equipment limit",
    "O2_TOTAL_LIMIT": "Projected cumulative oxygen exceeds per-heat limit",
    "NO_CIRCULATION": "Steel circulation not established",
    "CHEM_HEATING_DISABLED": "Chemical heating not enabled/validated for this plant",
    "GRADE_NOT_RHOB_SUITABLE": "Grade card forbids oxygen blowing",
}


@dataclass
class ValidationIssue:
    severity: str
    message: str


def validate_schedule(schedule, plant) -> list[ValidationIssue]:
    issues = []
    prev = None
    for ph in schedule.phases:
        if ph.stage not in STAGES:
            issues.append(ValidationIssue("error", f"unknown stage '{ph.stage}'"))
            continue
        if ph.stage not in ALLOWED_TRANSITIONS.get(prev, set()):
            issues.append(ValidationIssue("error", f"transition {prev} -> {ph.stage} not permitted by configured sequence"))
        if ph.oxygen_Nm3_h > 0 and ph.stage not in ("OB_DECARB", "CHEMICAL_HEATING"):
            issues.append(ValidationIssue("error", f"oxygen requested in stage {ph.stage}; only OB_DECARB/CHEMICAL_HEATING may blow"))
        if ph.oxygen_Nm3_h > plant.limits.oxygen_max_Nm3_h:
            issues.append(ValidationIssue("error", f"{ph.stage}: O2 {ph.oxygen_Nm3_h} Nm3/h > limit {plant.limits.oxygen_max_Nm3_h}"))
        if ph.snorkels_immersed and ph.argon_NL_min < plant.limits.argon_min_NL_min and ph.stage not in ("ARRIVAL_CHECKS",):
            issues.append(ValidationIssue("warning", f"{ph.stage}: argon {ph.argon_NL_min} NL/min below nozzle keep-open minimum"))
        if ph.argon_NL_min > plant.limits.argon_max_NL_min:
            issues.append(ValidationIssue("error", f"{ph.stage}: argon above maximum"))
        if ph.vent and ph.vacuum_pump_on:
            issues.append(ValidationIssue("error", f"{ph.stage}: conflicting commands (vent valve open with pumps on)"))
        if ph.stage == "DISPATCH" and ph.snorkels_immersed:
            issues.append(ValidationIssue("error", "DISPATCH requires snorkels withdrawn"))
        if ph.pressure_setpoint_Pa < plant.limits.pressure_min_Pa or (ph.pressure_setpoint_end_Pa or 1e9) < plant.limits.pressure_min_Pa:
            issues.append(ValidationIssue("warning", f"{ph.stage}: pressure set-point below controllable minimum; pump capacity will decide"))
        prev = ph.stage
    tot_o2 = sum(ph.oxygen_Nm3_h * ph.duration_s / 3600 for ph in schedule.phases)
    if tot_o2 > plant.limits.oxygen_max_total_Nm3:
        issues.append(ValidationIssue("error", f"scheduled oxygen {tot_o2:.0f} Nm3 > per-heat limit"))
    T = sum(ph.duration_s for ph in schedule.phases if ph.stage != "DISPATCH")
    if T > plant.limits.max_treatment_time_s:
        issues.append(ValidationIssue("warning", f"treatment time {T:.0f} s exceeds max {plant.limits.max_treatment_time_s:.0f} s"))
    for a in schedule.additions:
        if a.t_s > sum(ph.duration_s for ph in schedule.phases):
            issues.append(ValidationIssue("error", f"addition at {a.t_s}s after schedule end"))
    return issues


def make_guard(plant, grade=None):
    """Return guard(model, phase, prev_phase) -> (ok, reason_code)."""
    lim = plant.limits

    def guard(model, ph, prev):
        if ph["oxygen_Nm3_h"] <= 0:
            if ph["stage"] == "CHEMICAL_HEATING" and not plant.chemical_heating_enabled:
                return False, "CHEM_HEATING_DISABLED"
            return True, None
        if plant.variant.value != "RH_OB" or plant.geometry.oxygen_tuyere_count == 0:
            return False, "O2_NOT_INSTALLED"
        if grade is not None and not getattr(grade, "rh_ob_suitable", True):
            return False, "GRADE_NOT_RHOB_SUITABLE"
        if not lim.oxygen_safety_prerequisites_confirmed:
            return False, "O2_SAFETY_PREREQ_UNKNOWN"
        if ph["stage"] == "CHEMICAL_HEATING" and not plant.chemical_heating_enabled:
            return False, "CHEM_HEATING_DISABLED"
        if ph["oxygen_Nm3_h"] > lim.oxygen_max_Nm3_h:
            return False, "O2_FLOW_LIMIT"
        _, D = model._f(model.t, model.y, True)
        if D["vessel_depth_m"] < lim.oxygen_min_vessel_depth_m:
            return False, "O2_VESSEL_DEPTH_LOW"
        if D["P_Pa"] > lim.oxygen_max_vessel_pressure_Pa:
            return False, "O2_PRESSURE_HIGH"
        if D["q_circ_kg_s"] <= 0:
            return False, "NO_CIRCULATION"
        used = model.y[model.L["acc_o2_tuyere"]] * 0.022414
        proj = used + ph["oxygen_Nm3_h"] * (ph["t_end"] - ph["t_start"]) / 3600
        if proj > lim.oxygen_max_total_Nm3 + 1e-6:
            return False, "O2_TOTAL_LIMIT"
        return True, None

    return guard
