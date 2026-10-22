"""Equipment geometry: capacity presets, derived dimensions, hydrostatics.

Presets are ILLUSTRATIVE engineering proportions for demonstration (no OEM drawing was
used). A plant replaces them with as-built drawings (OPTIONAL CONFIGURATION FORM).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.units import G_ACC

# capacity [t] -> illustrative dimensions
_PRESET_TABLE = {
    #  t : ladle_D, snorkel_D, snorkel_L, immersion, vessel_D, vessel_H, duct_V, Ar_nom NL/min, O2_max Nm3/h, pump_scale
    100: (2.85, 0.45, 1.25, 0.50, 2.00, 8.0, 45.0, 1000.0, 1200.0, 0.40),
    150: (3.20, 0.50, 1.30, 0.50, 2.30, 8.8, 55.0, 1300.0, 1600.0, 0.55),
    200: (3.45, 0.60, 1.35, 0.55, 2.60, 9.5, 65.0, 1700.0, 2000.0, 0.70),
    250: (3.65, 0.65, 1.40, 0.55, 2.80, 10.0, 75.0, 2100.0, 2500.0, 0.85),
    300: (3.85, 0.75, 1.45, 0.55, 3.00, 10.5, 85.0, 2500.0, 3000.0, 1.00),
    350: (4.05, 0.80, 1.50, 0.60, 3.20, 11.0, 95.0, 2800.0, 3400.0, 1.15),
}
PRESET_CAPACITIES = sorted(_PRESET_TABLE)

# Reference pump curve for the 300 t preset: suction absolute pressure [Pa] vs
# dry-air-equivalent capacity [kg/h] (ILLUSTRATIVE multi-stage steam ejector + LRVP)
REF_PUMP_CURVE = [
    [40.0, 0.0], [67.0, 900.0], [133.0, 1350.0], [400.0, 2050.0], [1000.0, 2700.0],
    [4000.0, 3800.0], [10000.0, 4600.0], [30000.0, 5600.0], [101325.0, 6500.0],
]


def preset_for_capacity(capacity_t: float) -> dict:
    caps = np.array(PRESET_CAPACITIES, dtype=float)
    rows = np.array([_PRESET_TABLE[c] for c in PRESET_CAPACITIES])
    vals = [float(np.interp(capacity_t, caps, rows[:, j])) for j in range(rows.shape[1])]
    keys = ["ladle_inner_diameter_m", "snorkel_inner_diameter_m", "snorkel_length_m",
            "immersion_depth_m", "vessel_inner_diameter_m", "vessel_height_m",
            "duct_and_cooler_volume_m3", "argon_nominal_NL_min", "oxygen_max_Nm3_h", "pump_scale"]
    d = dict(zip(keys, vals))
    d["capacity_t"] = capacity_t
    d["pump_curve"] = [[p, w * d["pump_scale"]] for p, w in REF_PUMP_CURVE]
    return d


@dataclass
class DerivedGeometry:
    A_ladle: float           # ladle cross-section, m2
    bath_depth_ladle: float  # nominal (all steel in ladle), m
    A_vessel: float
    A_snorkel: float
    r_ladle: float
    r_vessel: float
    h_vb0: float             # vessel bottom height above ladle steel level (no steel lifted), m
    V_vessel_internal: float
    A_ladle_wall: float      # wetted side+bottom area, m2
    A_ladle_top_open: float  # ladle top open area (minus snorkel footprints), m2
    A_vessel_lower_wall: float
    A_vessel_upper_wall: float
    nozzle_depth_below_level: float


def derive(geom: dict, steel_mass_kg: float, rho: float = 7000.0) -> DerivedGeometry:
    D_l = geom["ladle_inner_diameter_m"]
    A_l = math.pi * D_l ** 2 / 4.0
    H_bath = steel_mass_kg / rho / A_l
    D_v = geom["vessel_inner_diameter_m"]
    A_v = math.pi * D_v ** 2 / 4.0
    D_s = geom["snorkel_inner_diameter_m"]
    A_s = math.pi * D_s ** 2 / 4.0
    h_vb0 = geom["snorkel_length_m"] - geom["immersion_depth_m"]
    V_int = A_v * geom["vessel_height_m"]
    A_wall_l = math.pi * D_l * H_bath + A_l
    D_s_out = D_s + 2 * geom.get("snorkel_wall_thickness_m", 0.25)
    A_top = max(A_l - 2 * math.pi * D_s_out ** 2 / 4.0, 0.2 * A_l)
    lower_h = geom.get("vessel_lower_height_m", 2.5)
    A_low = math.pi * D_v * lower_h + A_v + 2 * math.pi * D_s * geom["snorkel_length_m"]
    A_up = math.pi * D_v * max(geom["vessel_height_m"] - lower_h, 1.0) + A_v
    nozzle_depth = geom["immersion_depth_m"] - geom.get("lift_nozzle_height_above_tip_m", 0.20)
    return DerivedGeometry(A_l, H_bath, A_v, A_s, D_l / 2, D_v / 2, h_vb0, V_int, A_wall_l, A_top,
                           A_low, A_up, max(nozzle_depth, 0.05))


def barometric_height(p_atm: float, p_vessel: float, rho: float) -> float:
    """Height [m] that steel rises above the ladle level at vessel pressure p_vessel."""
    return max(p_atm - p_vessel, 0.0) / (rho * G_ACC)


def vessel_holdup_equilibrium(dg: DerivedGeometry, p_atm: float, p_vessel: float, rho: float,
                              immersion: float, snorkels_immersed: bool) -> tuple[float, float, float]:
    """Steel hold-up (kg) in snorkels + vessel at hydrostatic equilibrium.

    Returns (M_v_eq, bath_depth_in_vessel_m, ladle_level_drop_m). The ladle level drop
    caused by lifting steel is included by one fixed-point correction (it reduces the
    barometric lift relative to the vessel bottom).
    """
    if not snorkels_immersed:
        return 0.0, 0.0, 0.0
    h_b = barometric_height(p_atm, p_vessel, rho)
    drop = 0.0
    M = 0.0
    depth = 0.0
    for _ in range(3):
        h_vb = dg.h_vb0 + drop  # level drop lifts the vessel bottom relative to ladle level
        imm = max(immersion - drop, 0.0)
        col = min(h_b, h_vb)  # snorkel column above ladle level
        m_sn = rho * 2.0 * dg.A_snorkel * (imm + col)
        depth = max(h_b - h_vb, 0.0)
        m_vs = rho * dg.A_vessel * depth
        M = m_sn + m_vs
        drop = (M - rho * 2 * dg.A_snorkel * immersion) / (rho * dg.A_ladle)
    return M, depth, drop
