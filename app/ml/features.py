"""Feature definitions for the hybrid residual model (with provenance).

Every feature must be available AT DECISION TIME (end of deep vacuum, before deoxidation):
no leakage of endpoint information. Provenance labels say where a plant would get it.
"""
from __future__ import annotations

FEATURES = [
    ("C0_ppm", "LAB ANALYZED", "arrival sample"),
    ("O0_ppm", "MEASURED", "O-activity probe at arrival"),
    ("T0_K", "MEASURED", "dip thermocouple at arrival"),
    ("H0_ppm", "MEASURED", "Hydris-type probe or estimate"),
    ("N0_ppm", "LAB ANALYZED", "arrival sample"),
    ("mass_t", "MEASURED", "ladle weighing"),
    ("V_O2_Nm3", "MEASURED", "O2 flow totalizer"),
    ("t_deep_s", "USER-DEFINED", "schedule"),
    ("argon_NL_min", "MEASURED", "Ar flowmeter"),
    ("P_deep_Pa", "MEASURED", "vacuum transmitter"),
    ("leak_kg_h", "ESTIMATED", "leak test"),
    ("fouling", "ESTIMATED", "nozzle back-pressure"),
    ("snorkel_age_heats", "MEASURED", "maintenance system"),
    ("ladle_idle_min", "MEASURED", "ladle tracking"),
    ("twin_C_end_ppm", "PREDICTED", "physics twin"),
    ("twin_T_end_K", "PREDICTED", "physics twin"),
    ("twin_Kapp_1_min", "PREDICTED", "physics twin"),
]
FEATURE_NAMES = [f[0] for f in FEATURES]
TARGETS = ["resid_lnC", "resid_T_K"]


def provenance_check(row: dict) -> list[str]:
    """Return list of missing/invalid features (feature-provenance check)."""
    bad = []
    for name, _, _ in FEATURES:
        v = row.get(name)
        if v is None or (isinstance(v, float) and v != v):
            bad.append(name)
    return bad
