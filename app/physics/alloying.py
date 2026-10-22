"""Alloy / deoxidizer additions: dissolution lag, yield, enthalpy.

Dissolution time constant from a melting-shell energy estimate (lump of radius r):
    tau_melt = rho_a r [cp_a (T_m - 298) + L_a] / (3 h_m (T_bath - T_m))      (T_bath > T_m)
For additions whose melting point is close to or above the bath temperature (FeNb, FeMo,
FeV, LC-FeCr) dissolution is solid-state diffusion/convective controlled:
    tau_diff = r rho_a / (3 rho_steel k_m X)  with an illustrative k_m = 2e-4 m/s
The rate is dm/dt = -m / tau. Enthalpy: material enters cold (h = 0 at 298 K) and is
heated/melted by the steel when it dissolves (absorbs h_steel(T) per kg via the enthalpy
mixing rule) + heat of solution (H_SOLUTION). Yield loss is removed at charge time into the
'additions loss' reservoir (recorded in the element ledger, not lost from the balance).
"""
from __future__ import annotations

from .properties import ADDITION_MATERIALS

H_M_CONV = 15_000.0  # W/(m2 K) steel -> lump convective coefficient in vessel (ILLUSTRATIVE)


def dissolution_tau(material: str, T_bath: float) -> float:
    m = ADDITION_MATERIALS[material]
    r = m["d_m"] / 2
    dT = T_bath - m["Tm"]
    tau_diff = r * m["rho"] / (3.0 * 7000.0 * 2e-4 * 0.5)
    if dT > 20.0:
        tau_melt = m["rho"] * r * (m["cp"] * (m["Tm"] - 298.0) + m["L"]) / (3.0 * H_M_CONV * dT)
        # shell freezing / remelting adds a lag of the same order
        return max(min(1.6 * tau_melt, tau_diff), 2.0)
    return max(tau_diff, 2.0)


def materials_catalog() -> dict:
    return {k: {"label": v["label"], "composition_wt_frac": v["comp"], "melting_K": v["Tm"],
                "lump_diameter_m": v["d_m"], "yield_default": v["yield_default"]}
            for k, v in ADDITION_MATERIALS.items()}
