"""Hazard & operating-limit registry and alarm evaluation.

Limits are taken from PlantConfig.limits (site-engineer supplied; demo placeholders). In the
cloud demo every interlock is a READ-ONLY SIMULATED indicator; the interlock owner is the
plant DCS/PLC. This module NEVER implements trip settings or bypass logic.
"""
from __future__ import annotations

HAZARDS = [
    {"id": "H01", "name": "High vessel pressure during vacuum stages", "severity": "warning", "source": "model/pressure transmitter",
     "detection": "P > 3 x set-point for > 60 s in DEEP_VACUUM/DEOXIDATION/HOMOGENIZATION",
     "operator_message": "Vacuum not attained - check ejector steam, condensers, leaks, CO load",
     "manual_response": "Check pump staging & steam pressure; reduce O2/argon if CO surge; inspect seals",
     "interlock_owner": "Vacuum system PLC", "inhibit": "Inhibit decarburization endpoint advice (low confidence)"},
    {"id": "H02", "name": "Pump-down failure", "severity": "alarm", "source": "pressure transmitter",
     "detection": "P > 30 kPa at end of PUMP_DOWN", "operator_message": "Cannot pump down - possible major leak / pump trip",
     "manual_response": "Abort per site procedure; do not start oxygen", "interlock_owner": "Vacuum system PLC",
     "inhibit": "Inhibit all oxygen recommendations"},
    {"id": "H03", "name": "Excess / unexpected oxygen flow", "severity": "alarm", "source": "O2 flowmeter",
     "detection": "O2 flow > limit or O2 > 0 outside OB/CHEMICAL_HEATING", "operator_message": "Oxygen flow outside permissive",
     "manual_response": "Close O2 valves per site procedure", "interlock_owner": "Oxygen valve train PLC (SIL-rated)",
     "inhibit": "READ_ONLY advisory"},
    {"id": "H04", "name": "Argon lift flow below keep-open minimum", "severity": "warning", "source": "Ar flowmeter",
     "detection": "Ar < min while snorkels immersed", "operator_message": "Low lift gas - nozzle blockage / circulation loss risk",
     "manual_response": "Check argon supply pressure & nozzle back-pressure", "interlock_owner": "Gas train PLC",
     "inhibit": "Flag circulation estimate low-confidence"},
    {"id": "H05", "name": "Circulation loss / nozzle fouling", "severity": "warning", "source": "model soft sensor",
     "detection": "circulation < 60 % of clean-nozzle value at same argon/vacuum", "operator_message": "Circulation degraded",
     "manual_response": "Inspect up-leg nozzles; consider snorkel maintenance", "interlock_owner": "n/a (advisory)",
     "inhibit": "Widen prediction intervals"},
    {"id": "H06", "name": "Insufficient snorkel immersion", "severity": "alarm", "source": "ladle lift position / model level",
     "detection": "effective immersion (immersion - level drop) < 0.20 m", "operator_message": "Snorkel immersion low - air ingress / splashing risk",
     "manual_response": "Raise ladle per site procedure", "interlock_owner": "Ladle lift PLC", "inhibit": "Inhibit O2 start"},
    {"id": "H07", "name": "Steel over-temperature", "severity": "warning", "source": "thermocouple / model",
     "detection": "T > limits.temperature_max_K", "operator_message": "Steel temperature high", "manual_response": "Stop chemical heating; plan coolant scrap",
     "interlock_owner": "n/a", "inhibit": "Inhibit chemical heating advice"},
    {"id": "H08", "name": "Steel under-temperature (freezing in snorkels)", "severity": "alarm", "source": "thermocouple / model",
     "detection": "T < limits.temperature_min_K", "operator_message": "Steel temperature low - snorkel skull/freezing risk",
     "manual_response": "Evaluate chemical heating (if validated) or end treatment early", "interlock_owner": "n/a",
     "inhibit": "Inhibit long holding advice"},
    {"id": "H09", "name": "Refractory over-temperature", "severity": "warning", "source": "model wall nodes / shell scanner",
     "detection": "ladle or vessel shell > 623 K or hot face > material max", "operator_message": "Refractory/shell temperature high",
     "manual_response": "Schedule shell inspection; check lining thickness", "interlock_owner": "Maintenance", "inhibit": "None"},
    {"id": "H10", "name": "CO accumulation at vacuum break", "severity": "alarm", "source": "off-gas analyzer",
     "detection": "x_CO > 0.25 when venting", "operator_message": "High CO in vessel at vacuum break",
     "manual_response": "Purge with N2/Ar before venting per site procedure", "interlock_owner": "Off-gas system PLC", "inhibit": "None"},
    {"id": "H11", "name": "Off-gas analyzer inconsistency", "severity": "warning", "source": "analyzer vs model",
     "detection": "|measured - model| carbon removal rate > 40 % for > 60 s", "operator_message": "Analyzer/model mismatch",
     "manual_response": "Check analyzer calibration, sampling line, wet/dry basis", "interlock_owner": "Instrumentation",
     "inhibit": "Do not use off-gas soft sensor"},
    {"id": "H12", "name": "Mass/energy balance violation", "severity": "alarm", "source": "model integrity",
     "detection": "closure residual > SolverConfig tolerances", "operator_message": "Model integrity check failed",
     "manual_response": "Treat predictions as invalid; notify process engineer", "interlock_owner": "n/a",
     "inhibit": "ADVISORY_INHIBITED"},
    {"id": "H13", "name": "Stale / invalid critical signal", "severity": "alarm", "source": "data layer",
     "detection": "no update > 3 x sample period or quality bit bad", "operator_message": "Stale data - recommendations paused",
     "manual_response": "Check communications", "interlock_owner": "OT network", "inhibit": "ADVISORY_INHIBITED"},
    {"id": "H14", "name": "Off-domain chemistry", "severity": "warning", "source": "validation",
     "detection": "composition outside model validity domain (dilute solution, T range)", "operator_message": "Outside model validity",
     "manual_response": "Use measured data only", "interlock_owner": "n/a", "inhibit": "ADVISORY_INHIBITED"},
    {"id": "H15", "name": "Oxygen safety prerequisites unknown", "severity": "alarm", "source": "simulated interlock",
     "detection": "limits.oxygen_safety_prerequisites_confirmed == False", "operator_message": "O2 prerequisites not confirmed",
     "manual_response": "Do not start oxygen", "interlock_owner": "Oxygen valve train PLC", "inhibit": "Never recommend oxygen start"},
    {"id": "H16", "name": "Personnel access / ladle lift / power / communications", "severity": "info", "source": "PLC (not simulated)",
     "detection": "Plant signals - UNAVAILABLE in demo", "operator_message": "Status from plant interlocks only",
     "manual_response": "Per site procedure", "interlock_owner": "Plant DCS/PLC", "inhibit": "READ_ONLY"},
]

VACUUM_STAGES = {"DEEP_VACUUM", "DEOXIDATION", "HOMOGENIZATION", "ALLOYING", "FINAL_SAMPLING", "CHEMICAL_HEATING"}


def evaluate_alarms(records: list, plant, closure_ok: bool = True, immersion: float | None = None) -> list[dict]:
    lim = plant.limits
    imm = immersion if immersion is not None else plant.geometry.immersion_depth_m
    out = []
    active = {}

    def raise_(hid, t, value, msg_extra=""):
        h = next(x for x in HAZARDS if x["id"] == hid)
        if hid in active and t - active[hid] < 120:
            return
        active[hid] = t
        out.append({"t_s": t, "id": hid, "name": h["name"], "severity": h["severity"], "value": value,
                    "message": h["operator_message"] + (f" ({msg_extra})" if msg_extra else ""),
                    "manual_response": h["manual_response"], "interlock_owner": h["interlock_owner"],
                    "inhibit": h["inhibit"], "simulated": True})

    high_p_since = None
    prev_stage = None
    for r in records:
        t, st = r["t_s"], r["stage"]
        P, Psp = r.get("P_Pa") or 0, r.get("P_sp_Pa") or 1
        if st in VACUUM_STAGES and P > 3 * Psp:
            high_p_since = high_p_since if high_p_since is not None else t
            if t - high_p_since >= 60:
                raise_("H01", t, P, f"P={P:.0f} Pa vs set-point {Psp:.0f} Pa")
        else:
            high_p_since = None
        if prev_stage == "PUMP_DOWN" and st != "PUMP_DOWN" and P > 30000:
            raise_("H02", t, P)
        o2 = r.get("oxygen_Nm3_h") or 0
        if o2 > lim.oxygen_max_Nm3_h + 1e-6 or (o2 > 0 and st not in ("OB_DECARB", "CHEMICAL_HEATING")):
            raise_("H03", t, o2)
        if st not in ("ARRIVAL_CHECKS", "DISPATCH") and (r.get("argon_NL_min") or 0) < lim.argon_min_NL_min and st != "VACUUM_BREAK":
            raise_("H04", t, r.get("argon_NL_min"))
        qr = r.get("q_raw_t_min") or 0
        if plant.kinetics.lift_nozzle_fouling < 0.6 and (r.get("q_circ_t_min") or 0) > 0:
            raise_("H05", t, plant.kinetics.lift_nozzle_fouling, "nozzle fouling factor")
        drop = r.get("ladle_level_drop_m") or 0
        if st not in ("ARRIVAL_CHECKS", "DISPATCH") and imm - drop < 0.20:
            raise_("H06", t, imm - drop)
        T = r.get("T_bulk_K") or 0
        if T > lim.temperature_max_K:
            raise_("H07", t, T)
        if 0 < T < lim.temperature_min_K and st != "DISPATCH":
            raise_("H08", t, T)
        if (r.get("T_ladle_shell_K") or 0) > 623 or (r.get("T_vlow_shell_K") or 0) > 623:
            raise_("H09", t, max(r.get("T_ladle_shell_K") or 0, r.get("T_vlow_shell_K") or 0))
        if st in ("VACUUM_BREAK", "ABORT_VACUUM_BREAK") and (r.get("x_CO") or 0) > 0.25:
            raise_("H10", t, r.get("x_CO"))
        prev_stage = st
    if not closure_ok:
        raise_("H12", records[-1]["t_s"] if records else 0.0, None)
    if not lim.oxygen_safety_prerequisites_confirmed:
        raise_("H15", 0.0, None)
    return out
