"""Vacuum decarburization  [C] + [O] = CO(g)  at three reaction sites.

Site 1  FREE SURFACE of the vessel bath (including splash/droplet enhancement):
        mixed transport control of C and O to an interface at p_CO = x_CO * Pv.
        The interface concentrations satisfy  C_i * O_i = m(p_CO) / (f_C f_O)  and the
        stoichiometric flux balance  kO (O - O_i) = (M_O/M_C) kC (C - C_i).  This gives a
        closed-form quadratic (``mixed_control_interface``).  The flux vanishes exactly
        at equilibrium and changes rate-limiting step automatically:
          - high C, low O  -> O transport controls (OB supplies O)
          - ULC, excess O  -> C transport controls (classical first-order regime)
Site 2  IN-BATH CO NUCLEATION (inner site): active where the equilibrium CO pressure
        exceeds the local hydrostatic pressure Pv + rho g z plus a nucleation
        over-pressure. Active depth z* -> active volume; it disappears in the ULC regime.
Site 3  ARGON LIFT BUBBLES: bubbles rising from P1 to Pv approach equilibrium with
        C/O (and H, N - see degassing_hn) by a factor eps; CO pick-up per mol Ar is
        p_eq/(P_b - sum p_eq), bounded so that sum p_eq <= 0.9 P_b, and bounded by the
        carbon convected through the up-leg.

All rates returned in mol C / s (= mol CO / s) and are >= 0 when decarburization is
thermodynamically favoured; if the bath is below equilibrium the rate is exactly 0
(no reverse carburization from CO - documented assumption).
"""
from __future__ import annotations

import math

from ..core.units import G_ACC
from .properties import MW
from .thermodynamics import K

R_OC = MW["O"] / MW["C"]


def mixed_control_interface(C: float, O: float, m: float, kC_cap: float, kO_cap: float) -> float:
    """Return carbon flux [kg C/s].

    C, O bulk [wt%]; m = equilibrium product C_i*O_i [wt%^2] at the interface;
    kC_cap, kO_cap = rho*k*A [kg/s] (transport capacities).
    """
    if C <= 0 or O <= 0 or C * O <= m or kC_cap <= 0 or kO_cap <= 0:
        return 0.0
    r = R_OC * kC_cap / kO_cap
    b = O - r * C
    Ci = (-b + math.sqrt(b * b + 4.0 * r * m)) / (2.0 * r)
    Ci = min(max(Ci, 0.0), C)
    return kC_cap * (C - Ci) / 100.0


def surface_site(C, O, T, Pv, x_co, fC, fO, rho, A_surface, kin) -> float:
    if A_surface <= 0:
        return 0.0
    p_co = max(x_co * Pv, 1e-3)
    m = (p_co / 101_325.0) / (K("C_O_CO", T) * fC * fO)
    kC = rho * kin.k_C_surface_m_s * A_surface
    kO = kC * kin.kO_over_kC
    return mixed_control_interface(C, O, m, kC, kO) / MW["C"]  # mol/s


def inner_site(C, O, T, Pv, fC, fO, rho, A_vessel, depth, kin) -> tuple[float, float]:
    """Returns (rate mol C/s, active depth m)."""
    if depth <= 0 or kin.inner_site_rate_1_s <= 0:
        return 0.0, 0.0
    p_eq = K("C_O_CO", T) * fC * fO * max(C, 0) * max(O, 0) * 101_325.0
    z_star = (p_eq - Pv - kin.co_nucleation_overpressure_Pa) / (rho * G_ACC)
    z_star = min(max(z_star, 0.0), depth)
    if z_star <= 0:
        return 0.0, 0.0
    p_mid = Pv + kin.co_nucleation_overpressure_Pa + 0.5 * rho * G_ACC * z_star
    m = (p_mid / 101_325.0) / (K("C_O_CO", T) * fC * fO)
    V = A_vessel * z_star
    kC = rho * V * kin.inner_site_rate_1_s * 1.0  # [kg/s] volumetric capacity ("k a V rho")
    kO = kC * kin.kO_over_kC
    return mixed_control_interface(C, O, m, kC, kO) / MW["C"], z_star


def bubble_partial_pressures(C, O, T, fC, fO, p_h2_eq, p_n2_eq_eff) -> dict:
    p_co = K("C_O_CO", T) * fC * fO * max(C, 0) * max(O, 0) * 101_325.0
    return {"CO": p_co, "H2": p_h2_eq, "N2": p_n2_eq_eff}


def bubble_site(n_ar: float, P_b: float, p_eq: dict, eps: float, q_c: float, C_up_frac: float) -> dict:
    """Moles/s of CO, H2, N2 removed by Ar lift bubbles.

    n_ar      lift gas actually entering the up-leg [mol/s]
    P_b       log-mean bubble pressure [Pa]
    p_eq      equilibrium partial pressures [Pa] with the up-leg melt
    C_up_frac carbon mass fraction entering the up-leg (convective limit)
    """
    out = {"CO": 0.0, "H2": 0.0, "N2": 0.0, "capped": False}
    if n_ar <= 0 or P_b <= 0 or eps <= 0:
        return out
    tot = sum(max(v, 0.0) for v in p_eq.values())
    scale = 1.0
    if tot > 0.9 * P_b:
        scale = 0.9 * P_b / tot
        out["capped"] = True
    denom = P_b - scale * tot
    for k, v in p_eq.items():
        out[k] = eps * n_ar * scale * max(v, 0.0) / denom
    # convective carbon limit: cannot remove more C than flows through the up-leg
    c_lim = q_c * max(C_up_frac, 0.0) / MW["C"] * 0.5
    if out["CO"] > c_lim:
        out["CO"] = c_lim
        out["capped"] = True
    return out


def apparent_rate_constant(q_c: float, M: float, rho: float, ak: float) -> float:
    """Classical lumped RH first-order decarburization constant K [1/s]
    (Kuwabara et al. 1988):  K = (Q/W) * (rho a k) / (Q + rho a k). Used for display and
    for the reduced-order estimator, NOT by the dynamic model which resolves the sites."""
    if q_c <= 0 or M <= 0:
        return 0.0
    rak = rho * ak
    return (q_c / M) * rak / (q_c + rak)
