"""Economic objective (soft goals) for feasible plans. All prices are ILLUSTRATIVE config values."""
from __future__ import annotations

from ..services.reporting import rh_end_record


def economic_cost(records: list, plant, grade, applied_additions: list) -> dict:
    e = rh_end_record(records)
    eco = plant.economics
    t_min = e["t_s"] / 60.0
    o2 = e.get("cum_O2_Nm3") or 0.0
    ar = e.get("cum_Ar_Nm3") or 0.0
    steam_t = (e.get("cum_exhaust_kg") or 0.0) * eco.steam_kg_per_kg_gas / 1000.0
    alloys = sum(a["mass_kg"] * eco.alloy_prices_per_kg.get(a["material"], 0.0) for a in applied_additions)
    terms = {"time_refractory": t_min * eco.refractory_per_min, "oxygen": o2 * eco.oxygen_per_Nm3,
             "argon": ar * eco.argon_per_Nm3, "steam": steam_t * eco.steam_per_t, "alloys": alloys}
    if grade is not None:
        t_target = 0.5 * (grade.T_end_min_K + grade.T_end_max_K)
        terms["temperature_deviation"] = 40.0 * (e["T_bulk_K"] - t_target) ** 2
    terms["total"] = sum(terms.values())
    return terms
