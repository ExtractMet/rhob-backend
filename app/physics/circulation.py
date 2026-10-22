"""Steel circulation through the snorkels driven by argon gas lift.

Two selectable models (KineticsConfig.circulation_model):

1. "kuwabara"   Empirical correlation of Kuwabara et al., Trans. ISIJ 28 (1988) 305-314:
        Q [t/min] = 11.4 * G^(1/3) * D^(4/3) * [ln(P1/Pv)]^(1/3)
   G  lift gas [NL/min] (normal litres),  D  up-leg inner diameter [m],
   P1 absolute pressure at the gas injection point [Pa], Pv vessel pressure [Pa].

2. "energy_balance"  Physically based gas-lift pump: a fraction eta of the isothermal
   expansion work of the lift gas between P1 and Pv sustains the kinetic-energy losses of
   the loop (loss coefficient zeta referred to snorkel velocity u = Q/(rho A)):
        eta * n_g R T ln(P1/Pv) = 0.5 * zeta * rho * u^2 * (Q/rho)
     => Q = rho A [2 eta n_g R T ln(P1/Pv) / (zeta rho A)]^(1/3)
   This reproduces the G^(1/3) [ln(P1/Pv)]^(1/3) scaling of (1) from first principles,
   which is why the two models can be cross-calibrated.

Common corrections (both models):
  * G is multiplied by the nozzle fouling factor theta (0..1).
  * hydraulic saturation: Q_eff = Q / (1 + (Q/Q_max)^4)^(1/4), Q_max = rho A u_max.
  * circulation requires a steel pool in the vessel: smooth factor of vessel bath depth.
  * calibration multiplier c_Q (tracer / mixing-time tests) with stated 1-sigma.
"""
from __future__ import annotations

import math

from ..core.units import G_ACC, R_GAS, nl_min_to_mol_s


def injection_pressure(p_atm: float, rho: float, nozzle_depth_below_level: float) -> float:
    return p_atm + rho * G_ACC * nozzle_depth_below_level


def kuwabara_t_min(G_nl_min: float, D_up: float, P1: float, Pv: float) -> float:
    if G_nl_min <= 0 or P1 <= Pv:
        return 0.0
    return 11.4 * G_nl_min ** (1 / 3) * D_up ** (4 / 3) * math.log(P1 / Pv) ** (1 / 3)


def energy_balance_kg_s(G_nl_min: float, D_up: float, P1: float, Pv: float, rho: float, T_gas: float,
                        eta: float, zeta: float) -> float:
    if G_nl_min <= 0 or P1 <= Pv:
        return 0.0
    A = math.pi * D_up ** 2 / 4
    n = nl_min_to_mol_s(G_nl_min)
    work = eta * n * R_GAS * T_gas * math.log(P1 / Pv)  # W
    u = (2.0 * work / (zeta * rho * A)) ** (1 / 3)
    return rho * A * u


def circulation_rate(kin, G_nl_min: float, D_up: float, P1: float, Pv: float, rho: float,
                     T_steel: float, vessel_depth: float) -> dict:
    """Circulation rate [kg/s] and diagnostics."""
    G_eff = G_nl_min * kin.lift_nozzle_fouling
    if kin.circulation_model == "kuwabara":
        q_raw = kuwabara_t_min(G_eff, D_up, P1, Pv) * 1000.0 / 60.0
    else:
        q_raw = energy_balance_kg_s(G_eff, D_up, P1, Pv, rho, T_steel, kin.energy_balance_efficiency,
                                    kin.energy_balance_loss_coeff)
    A = math.pi * D_up ** 2 / 4
    q_max = rho * A * kin.downleg_velocity_max_m_s
    q_sat = q_raw / (1.0 + (q_raw / q_max) ** 4) ** 0.25 if q_raw > 0 else 0.0
    # vessel pool factor (smooth ramp 0 -> 1 over the first 0.10 m of vessel bath)
    x = max(min(vessel_depth / 0.10, 1.0), 0.0)
    pool = x * x * (3 - 2 * x)
    q = kin.circulation_multiplier * q_sat * pool
    return {"q_kg_s": q, "q_raw_kg_s": q_raw, "q_max_kg_s": q_max, "pool_factor": pool,
            "G_eff_NL_min": G_eff, "u_downleg_m_s": q / (rho * A) if A > 0 else 0.0,
            "saturation_ratio": (q_sat / q_raw) if q_raw > 0 else 1.0}


def gas_holdup_upleg(G_nl_min: float, D_up: float, P_mean: float, T: float, u_liquid: float) -> float:
    """Drift-flux estimate of mean gas hold-up in the up-leg (Zuber-Findlay, C0=1.2,
    drift velocity 0.35 m/s for large cap bubbles). Used for display and inclusion capture."""
    if G_nl_min <= 0:
        return 0.0
    A = math.pi * D_up ** 2 / 4
    j_g = nl_min_to_mol_s(G_nl_min) * R_GAS * T / max(P_mean, 1.0) / A
    v_g = 1.2 * (j_g + u_liquid) + 0.35
    return min(j_g / v_g, 0.6)
