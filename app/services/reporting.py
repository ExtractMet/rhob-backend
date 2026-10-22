"""Endpoint evaluation, KPIs, advisory cards and heat reports."""
from __future__ import annotations

import math
from typing import Optional

from ..physics.properties import ADDITION_MATERIALS

RH_END_STAGES = ("VACUUM_BREAK", "ABORT_VACUUM_BREAK")


def rh_end_record(records: list) -> dict:
    """Record at the end of vacuum treatment (start of vacuum break) - the RH departure state."""
    cand = [r for r in records if r["stage"] in RH_END_STAGES]
    if cand:
        first = cand[0]["t_s"]
        before = [r for r in records if r["t_s"] <= first]
        return before[-1]
    nondispatch = [r for r in records if r["stage"] != "DISPATCH"]
    return nondispatch[-1] if nondispatch else records[-1]


def first_time_below(records: list, key: str, thr: float) -> Optional[float]:
    for r in records:
        v = r.get(key)
        if v is not None and v <= thr and r["stage"] not in ("ARRIVAL_CHECKS",):
            return r["t_s"]
    return None


def evaluate_endpoint(records: list, grade, plant, applied_additions: list | None = None) -> dict:
    if not records:
        return {}
    end = rh_end_record(records)
    last = records[-1]
    checks = []

    def chk(name, value, lo, hi, unit, prio):
        ok = (lo is None or value >= lo) and (hi is None or value <= hi)
        checks.append({"target": name, "value": value, "min": lo, "max": hi, "unit": unit, "ok": ok, "priority": prio})

    if grade is not None:
        chk("C", end["C_bulk_ppm"], None, grade.C_max_ppm, "ppm", "hard-quality")
        chk("N", end["N_bulk_ppm"], None, grade.N_max_ppm, "ppm", "hard-quality")
        chk("H", end["H_bulk_ppm"], None, grade.H_max_ppm, "ppm", "hard-quality")
        if (end.get("Al_bulk_ppm") or 0) > 50:
            chk("O_dissolved_after_deox", end["O_bulk_ppm"], None, grade.O_diss_max_after_deox_ppm, "ppm", "hard-quality")
        chk("Al", end["Al_bulk_ppm"] / 1e4, grade.Al_min_wtpct, grade.Al_max_wtpct, "wt%", "hard-quality")
        if grade.Si_max_wtpct is not None:
            chk("Si", end["Si_bulk_ppm"] / 1e4, None, grade.Si_max_wtpct, "wt%", "hard-quality")
        if grade.Mn_min_wtpct is not None or grade.Mn_max_wtpct is not None:
            chk("Mn", end["Mn_bulk_ppm"] / 1e4, grade.Mn_min_wtpct, grade.Mn_max_wtpct, "wt%", "hard-quality")
        if grade.Ti_min_wtpct is not None:
            chk("Ti", end["Ti_bulk_ppm"] / 1e4, grade.Ti_min_wtpct, grade.Ti_max_wtpct, "wt%", "hard-quality")
        chk("T_RH_end", end["T_bulk_K"], grade.T_end_min_K, grade.T_end_max_K, "K", "hard-quality")
        t_treat = end["t_s"]
        chk("treatment_time", t_treat, None, min(grade.max_treatment_time_s, plant.limits.max_treatment_time_s), "s", "hard-production")
        if grade.total_oxygen_max_ppm is not None:
            chk("total_O_predicted", last.get("total_O_ppm") or 0.0, None, grade.total_oxygen_max_ppm, "ppm", "indicator (PREDICTED, uncertain)")
        sh = last.get("superheat_K")
        if sh is not None:
            # ladle superheat at caster arrival = tundish target + ladle-to-tundish loss (~20 K, ILLUSTRATIVE)
            chk("caster_superheat", sh, grade.caster_superheat_target_K + 10, grade.caster_superheat_target_K + 30, "K", "soft")
    hard_fail = [c for c in checks if not c["ok"] and c["priority"].startswith("hard")]
    reasons = []
    for c in hard_fail:
        reasons.append(_reason(c, records, end))
    t_C = first_time_below(records, "C_bulk_ppm", grade.C_max_ppm) if grade else None
    t_H = first_time_below(records, "H_bulk_ppm", grade.H_max_ppm) if grade else None
    t_N = first_time_below(records, "N_bulk_ppm", grade.N_max_ppm) if grade else None
    return {"rh_end_t_s": end["t_s"], "caster_arrival_t_s": last["t_s"], "checks": checks,
            "feasible": len(hard_fail) == 0, "infeasibility_reasons": reasons,
            "time_C_target_s": t_C, "time_H_target_s": t_H, "time_N_target_s": t_N,
            "rh_end_state": {k: end.get(k) for k in ["C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm", "Al_bulk_ppm",
                                                    "Si_bulk_ppm", "Mn_bulk_ppm", "Ti_bulk_ppm", "T_bulk_K", "total_O_ppm",
                                                    "M_total_kg"]},
            "caster_arrival_state": {k: last.get(k) for k in ["T_bulk_K", "superheat_K", "liquidus_K", "Al_bulk_ppm",
                                                             "N_bulk_ppm", "total_O_ppm"]}}


def _reason(c, records, end):
    t = c["target"]
    if t == "C":
        o_lim = (end.get("O_bulk_ppm") or 0) < 1.5 * (end.get("C_bulk_ppm") or 0) and (end.get("Al_bulk_ppm") or 0) < 50
        pre = [r for r in records if r["stage"] in ("DEEP_VACUUM",)]
        ol = pre[-1]["O_bulk_ppm"] < 1.5 * pre[-1]["C_bulk_ppm"] if pre else o_lim
        return {"target": "C", "why": ("oxygen-limited decarburization (dissolved O insufficient - oxygen supply needed)" if ol
                                       else "time/kinetics-limited decarburization (circulation x surface reaction capacity insufficient in the available time)"),
                "value": c["value"], "limit": c["max"]}
    if t == "N":
        return {"target": "N", "why": "nitrogen removal is second-order and poisoned by surface-active O/S; "
                                      "target below what vacuum degassing achieves in the available time", "value": c["value"], "limit": c["max"]}
    if t == "H":
        return {"target": "H", "why": "insufficient deep-vacuum time/pressure for hydrogen removal", "value": c["value"], "limit": c["max"]}
    if t == "T_RH_end":
        low = c["min"] is not None and c["value"] < c["min"]
        return {"target": "T", "why": "thermal deficit (losses exceed sources)" if low else "temperature above window",
                "value": c["value"], "limit": c["min"] if low else c["max"]}
    if t == "treatment_time":
        return {"target": "time", "why": "schedule exceeds permissible RH occupancy", "value": c["value"], "limit": c["max"]}
    return {"target": t, "why": "outside grade window", "value": c["value"], "limit": c["max"] if c["max"] is not None else c["min"]}


def compute_kpis(records: list, plant, applied_additions: list, heat_mass_t: float) -> dict:
    if not records:
        return {}
    end = rh_end_record(records)
    last = records[-1]
    eco = plant.economics
    o2 = end.get("cum_O2_Nm3") or 0.0
    ar = end.get("cum_Ar_Nm3") or 0.0
    gas_kg = end.get("cum_exhaust_kg") or 0.0
    steam_t = gas_kg * eco.steam_kg_per_kg_gas / 1000.0
    alloy_cost = 0.0
    alloy_kg = {}
    for a in applied_additions or []:
        alloy_kg[a["material"]] = alloy_kg.get(a["material"], 0.0) + a["mass_kg"]
        alloy_cost += a["mass_kg"] * eco.alloy_prices_per_kg.get(a["material"], 0.0)
    t_treat = end["t_s"]
    cost = {"oxygen": o2 * eco.oxygen_per_Nm3, "argon": ar * eco.argon_per_Nm3, "steam": steam_t * eco.steam_per_t,
            "alloys": alloy_cost, "refractory": t_treat / 60.0 * eco.refractory_per_min}
    first = records[0]
    vac = [r for r in records if r["stage"] in ("NATURAL_DECARB", "OB_DECARB", "DEEP_VACUUM")]
    Tdrop = None
    nonheat = [r for r in records if r["stage"] in ("DEEP_VACUUM", "HOMOGENIZATION")]
    if len(nonheat) > 2:
        Tdrop = (nonheat[0]["T_bulk_K"] - nonheat[-1]["T_bulk_K"]) / max(nonheat[-1]["t_s"] - nonheat[0]["t_s"], 1) * 60
    Kc = None
    if vac:
        Ks = [r.get("K_app_1_min") for r in vac if r.get("K_app_1_min")]
        Kc = sum(Ks) / len(Ks) if Ks else None
    total_cost = sum(cost.values())
    return {"currency": eco.currency, "treatment_time_min": t_treat / 60.0, "oxygen_Nm3": o2, "argon_Nm3": ar,
            "steam_t": steam_t, "steam_kg_per_t": steam_t * 1000 / heat_mass_t, "pumped_gas_kg": gas_kg,
            "alloys_kg": alloy_kg, "cost_breakdown": cost, "cost_total": total_cost, "cost_per_t": total_cost / heat_mass_t,
            "C_removal_pct": 100 * (1 - end["C_bulk_ppm"] / max(first["C_bulk_ppm"], 1e-9)),
            "H_removal_pct": 100 * (1 - end["H_bulk_ppm"] / max(first["H_bulk_ppm"], 1e-9)),
            "N_removal_pct": 100 * (1 - end["N_bulk_ppm"] / max(first["N_bulk_ppm"], 1e-9)),
            "mean_K_app_1_min": Kc, "T_drop_rate_K_min": Tdrop, "T_RH_end_C": end["T_bulk_K"] - 273.15,
            "T_caster_arrival_C": last["T_bulk_K"] - 273.15, "superheat_K": last.get("superheat_K"),
            "metal_yield_pct": 100 * (last.get("M_total_kg") or 0) / (heat_mass_t * 1000 + sum(alloy_kg.values())),
            "recirculation_number": end.get("recirculation_number"), "min_pressure_Pa": min(r["P_Pa"] for r in records),
            "mean_circulation_t_min": (sum(r["q_circ_t_min"] for r in vac) / len(vac)) if vac else None,
            "refractory_exposure_min": t_treat / 60.0}


def advisory_cards(records: list, grade, plant, endpoint: dict, alarms: list, mode: str, t_now: float) -> list[dict]:
    """Physics-derived recommendations (OPERATOR ADVISORY - human approval required)."""
    cards = []
    if not records or grade is None:
        return cards
    inhibited = any(a["inhibit"] in ("ADVISORY_INHIBITED",) and a["severity"] == "alarm" for a in alarms)
    end = rh_end_record(records)
    lim = plant.limits
    deep = [r for r in records if r["stage"] == "DEEP_VACUUM"]
    K = None
    if deep:
        K = (deep[-1].get("K_app_1_min") or 0.0) / 60.0
    base = {"approval": "Operator acknowledgement + shift metallurgist approval", "assumptions":
            "Nominal kinetics (uncalibrated demo); future pump capacity and argon as scheduled",
            "mode": mode, "inhibited": inhibited}
    C = end["C_bulk_ppm"]
    if C > grade.C_max_ppm:
        pre = deep[-1] if deep else end
        o_limited = pre["O_bulk_ppm"] < 1.5 * pre["C_bulk_ppm"]
        if o_limited and plant.variant.value == "RH_OB" and lim.oxygen_safety_prerequisites_confirmed and grade.rh_ob_suitable:
            need_o_ppm = (15.999 / 12.011) * (pre["C_bulk_ppm"] - 0.7 * grade.C_max_ppm) + 120 - pre["O_bulk_ppm"]
            M = pre["M_total_kg"]
            vol = max(need_o_ppm, 0) * 1e-6 * M / (1.429 * 0.85)
            cards.append({**base, "rank": 1, "title": "Add oxygen blowing (OB) during early decarburization",
                          "action": f"Schedule ~{vol:.0f} Nm3 O2 at {min(1800, lim.oxygen_max_Nm3_h):.0f} Nm3/h in OB_DECARB",
                          "expected_response": "Dissolved O supply sufficient for C+O->CO; endpoint C below grade max",
                          "uncertainty": "+/- 30 % on oxygen efficiency (eta_abs, jet partition uncalibrated)",
                          "affected_targets": ["C", "T (+ small exothermic gain)", "Al demand (higher O before deox)"],
                          "limiting_constraint": f"O2 per-heat limit {lim.oxygen_max_total_Nm3:.0f} Nm3; vessel P < {lim.oxygen_max_vessel_pressure_Pa:.0f} Pa",
                          "actuator_authority": "Operator via L1 oxygen station (manual)", "feasible": vol <= lim.oxygen_max_total_Nm3})
        elif K and K > 0:
            Ceq = pre.get("C_eq_surface_ppm") or 0.0
            tgt = 0.85 * grade.C_max_ppm
            dt = math.log(max(C - Ceq, 1e-6) / max(tgt - Ceq, 1e-6)) / K if tgt > Ceq else float("inf")
            feasible = end["t_s"] + dt <= min(grade.max_treatment_time_s, lim.max_treatment_time_s)
            cards.append({**base, "rank": 1, "title": "Extend deep-vacuum holding",
                          "action": f"Extend DEEP_VACUUM by ~{dt/60:.1f} min at minimum attainable pressure, full argon",
                          "expected_response": f"C from {C:.0f} to ~{tgt:.0f} ppm (first-order, K_app={K*60:.3f} 1/min)",
                          "uncertainty": "K_app +/- 22 % (circulation & surface-reaction uncalibrated)",
                          "affected_targets": ["C", "H", "N", "T (-1 K/min approx.)"],
                          "limiting_constraint": "treatment time / caster sequence", "actuator_authority": "Operator (schedule)",
                          "feasible": feasible})
    T = end["T_bulk_K"]
    if T < grade.T_end_min_K:
        dT = grade.T_end_min_K + 3 - T
        M = end["M_total_kg"]
        al = dT * M * 830 / (28.8e6 * 0.85)
        o2 = al / 26.982 * 0.75 * 0.022414 / 0.9
        if plant.chemical_heating_enabled and plant.variant.value == "RH_OB" and lim.oxygen_safety_prerequisites_confirmed:
            cards.append({**base, "rank": 2, "title": "Chemical heating (Al + O2)",
                          "action": f"Add ~{al:.0f} kg Al and blow ~{o2:.0f} Nm3 O2 after deoxidation",
                          "expected_response": f"+{dT:.1f} K (28.8 MJ/kg Al burnt to Al2O3 with gaseous O2)",
                          "uncertainty": "+/- 30 % (Al/O2 efficiency); increases Al2O3 inclusion load",
                          "affected_targets": ["T", "total O / cleanliness (worse)", "Al"],
                          "limiting_constraint": "O2 per-heat limit; cleanliness", "actuator_authority": "Metallurgist approval + operator",
                          "feasible": True})
        else:
            cards.append({**base, "rank": 2, "title": "Thermal deficit - no validated heating available",
                          "action": "Shorten holding time / request upstream temperature correction; report infeasibility",
                          "expected_response": "No in-RH heating source; endpoint T below window", "uncertainty": "+/- 4 K",
                          "affected_targets": ["T"], "limiting_constraint": "chemical heating disabled/not validated",
                          "actuator_authority": "None at RH (upstream)", "feasible": False})
    if T > grade.T_end_max_K:
        M = end["M_total_kg"]
        scrap = (T - grade.T_end_max_K + 2) * M * 830 / 1.4e6
        cards.append({**base, "rank": 3, "title": "Cooling scrap addition", "action": f"Add ~{scrap:.0f} kg clean cooling scrap via vacuum hopper",
                      "expected_response": f"-{T - grade.T_end_max_K + 2:.1f} K", "uncertainty": "+/- 20 %",
                      "affected_targets": ["T", "chemistry dilution (small)"], "limiting_constraint": "hopper capacity",
                      "actuator_authority": "Operator via alloy hopper", "feasible": True})
    if end["H_bulk_ppm"] > grade.H_max_ppm:
        cards.append({**base, "rank": 2, "title": "Extend degassing for hydrogen", "action": "Extend deep vacuum (P < 100 Pa) with full lift gas",
                      "expected_response": "H decays first-order towards Sieverts equilibrium", "uncertainty": "+/- 0.3 ppm",
                      "affected_targets": ["H", "T"], "limiting_constraint": "time", "actuator_authority": "Operator", "feasible": True})
    if end["N_bulk_ppm"] > grade.N_max_ppm:
        cards.append({**base, "rank": 3, "title": "Nitrogen target at risk", "action": "Keep deep vacuum after deoxidation (low O, S); avoid air leaks; use Ar for vacuum break",
                      "expected_response": "Limited: N removal is slow and poisoned by O/S", "uncertainty": "large",
                      "affected_targets": ["N"], "limiting_constraint": "kinetics (2nd order) - may be INFEASIBLE",
                      "actuator_authority": "Operator", "feasible": False})
    if any(a["id"] in ("H01", "H02") for a in alarms):
        cards.append({**base, "rank": 0, "title": "Low-confidence advisory: vacuum performance", "action": "Inspect ejector steam/condensers and seals; leak test at next opportunity",
                      "expected_response": "Restored pumping capacity", "uncertainty": "n/a", "affected_targets": ["C", "H", "N"],
                      "limiting_constraint": "pump capacity", "actuator_authority": "Maintenance", "feasible": True})
    if not cards:
        cards.append({**base, "rank": 9, "title": "Schedule meets all grade targets", "action": "Continue as scheduled; take final sample as planned",
                      "expected_response": "All hard targets satisfied (model prediction)", "uncertainty": "see prediction bands",
                      "affected_targets": [], "limiting_constraint": "-", "actuator_authority": "-", "feasible": True})
    for c in cards:
        if inhibited:
            c["title"] = "[INHIBITED] " + c["title"]
    return sorted(cards, key=lambda c: c["rank"])


def material_inputs_outputs(model) -> dict:
    """Inputs and outputs (weights and compositions) for the final heat report."""
    recs = model.records
    first, last = recs[0], recs[-1]
    y = model.y
    led = model.closure.element_ledger(y)
    from ..physics.properties import SLAG_OXIDES, SPECIES
    slag0 = {ox: first.get(f"slag_{ox}_kg") for ox in SLAG_OXIDES}
    slag1 = {ox: last.get(f"slag_{ox}_kg") for ox in SLAG_OXIDES}
    gas_out = {k.replace("cum_exh_", "").replace("_kg", ""): v for k, v in last.items() if k.startswith("cum_exh_")}
    return {
        "inputs": {
            "liquid_steel_t": model.M0 / 1000.0,
            "steel_composition_ppm": {s: first.get(f"{s}_bulk_ppm") for s in SPECIES},
            "steel_T_C": first["T_bulk_K"] - 273.15,
            "slag_kg": slag0,
            "oxygen_Nm3": last.get("cum_O2_Nm3"), "argon_Nm3": last.get("cum_Ar_Nm3"),
            "additions": model.applied_additions,
            "air_leak_and_vent": "included in off-gas/inputs ledger",
        },
        "outputs": {
            "liquid_steel_t": (last.get("M_total_kg") or 0) / 1000.0,
            "steel_composition_ppm": {s: last.get(f"{s}_bulk_ppm") for s in SPECIES},
            "steel_T_C": last["T_bulk_K"] - 273.15,
            "slag_kg": slag1,
            "offgas_kg": gas_out,
            "total_O_ppm_predicted": last.get("total_O_ppm"),
            "inclusions_ppm_by_class": last.get("inclusion_bins_ppm"),
        },
        "element_ledger_kg": led,
        "material_catalog": {k: v["label"] for k, v in ADDITION_MATERIALS.items()},
    }
