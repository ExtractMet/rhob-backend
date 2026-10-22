"""Constraint classes for the advisory optimizer.

Three separated classes (never traded against each other):
  1. HARD SAFETY / EQUIPMENT limits  -> enforced as variable BOUNDS and by the state-machine
     guards inside every simulation (an optimizer proposal can never exceed them).
  2. HARD PRODUCT-QUALITY acceptance -> inequality constraints g_i(x) >= 0 (lexicographic
     stage 1: feasibility first).
  3. SOFT ECONOMIC goals             -> objective (stage 2), only among feasible plans.
"""
from __future__ import annotations

from ..services.reporting import rh_end_record


def quality_constraints(records: list, grade, plant, margin: float = 0.9) -> dict:
    """Return {name: normalized margin}; >= 0 means satisfied."""
    e = rh_end_record(records)
    g = {}
    g["C"] = (margin * grade.C_max_ppm - e["C_bulk_ppm"]) / grade.C_max_ppm
    g["H"] = (margin * grade.H_max_ppm - e["H_bulk_ppm"]) / grade.H_max_ppm
    g["N"] = (grade.N_max_ppm - e["N_bulk_ppm"]) / grade.N_max_ppm
    g["T_min"] = (e["T_bulk_K"] - grade.T_end_min_K) / 10.0
    g["T_max"] = (grade.T_end_max_K - e["T_bulk_K"]) / 10.0
    tmax = min(grade.max_treatment_time_s, plant.limits.max_treatment_time_s)
    g["time"] = (tmax - e["t_s"]) / 300.0
    return g


def violation(g: dict) -> float:
    return sum(max(0.0, -v) for v in g.values())


def equipment_bounds(plant, has_ob: bool) -> dict:
    lim = plant.limits
    return {"V_O2_Nm3": (0.0, lim.oxygen_max_total_Nm3 if has_ob else 0.0),
            "t_deep_s": (240.0, 1800.0),
            "argon_NL_min": (lim.argon_min_NL_min, lim.argon_max_NL_min)}
