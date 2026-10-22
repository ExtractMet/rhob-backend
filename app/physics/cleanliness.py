"""Reduced-order alumina inclusion population (4 size classes per steel zone).

STATUS: PREDICTED, low confidence, uncalibrated. Outputs are model predictions, NOT a
cleanliness certification. Exogenous inclusions, re-entrainment of slag, clogging and
inclusion composition (spinel, Ca-aluminates) are NOT modelled -> declared UNAVAILABLE.

Mechanisms:
  * nucleation: Al2O3 from deoxidation enters class 0 (r = 2.5 um)
  * turbulent collision (Saffman-Turner): beta = 1.3 sqrt(eps/nu) (2r)^3 for equal sizes;
    pair collisions move mass from class k to class k+1 (mass conserving)
  * Stokes flotation to the slag (ladle) or vessel surface (vessel zone):
    u_k = 2 g dRho r_k^2 / (9 mu), removal rate u_k / H_zone
  * Ar bubble capture in the up-leg: k_b = kappa * Q_Ar[Nm3/s] * (r_k/10 um)^1.2 [1/s]
Total oxygen estimate: T.O. = dissolved O + O bound in suspended inclusions.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.units import G_ACC
from .properties import RHO_AL2O3, STEEL_KIN_VISC, STEEL_VISCOSITY, MW

R_BINS = np.array([2.5e-6, 7.5e-6, 20e-6, 50e-6])
N_BINS = len(R_BINS)
V_BINS = 4.0 / 3.0 * math.pi * R_BINS ** 3
O_FRAC_AL2O3 = 3 * MW["O"] / MW["Al2O3"]


def stokes_velocity(r: np.ndarray, rho_steel: float = 7000.0) -> np.ndarray:
    return 2.0 * G_ACC * (rho_steel - RHO_AL2O3) * r ** 2 / (9.0 * STEEL_VISCOSITY)


def inclusion_rates(m_bins: np.ndarray, M_zone: float, rho: float, eps_W_kg: float, H_zone: float,
                    q_ar_nm3_s: float, kappa_bub: float, agg_mult: float, bubble_zone: bool) -> tuple:
    """Return (dm_bins/dt [kg/s], removal_to_surface [kg/s], removal_by_bubbles [kg/s])."""
    dm = np.zeros(N_BINS)
    if M_zone <= 0:
        return dm, 0.0, 0.0
    V_steel = M_zone / rho
    m = np.maximum(m_bins, 0.0)
    num = m / (RHO_AL2O3 * V_BINS) / V_steel  # number density 1/m3
    # aggregation (equal-size collisions, class k -> k+1)
    G_t = math.sqrt(max(eps_W_kg, 0.0) / STEEL_KIN_VISC)
    for k in range(N_BINS - 1):
        beta = 1.3 * G_t * (2 * R_BINS[k]) ** 3 * agg_mult
        rate_pairs = 0.5 * beta * num[k] ** 2 * V_steel  # collisions/s
        dmass = rate_pairs * 2 * RHO_AL2O3 * V_BINS[k]
        dm[k] -= dmass
        dm[k + 1] += dmass
    # flotation
    u = stokes_velocity(R_BINS, rho)
    flot = u / max(H_zone, 0.05) * m
    dm -= flot
    # bubble capture
    bub = np.zeros(N_BINS)
    if bubble_zone and q_ar_nm3_s > 0:
        bub = kappa_bub * q_ar_nm3_s * (R_BINS / 10e-6) ** 1.2 * m
        dm -= bub
    return dm, float(np.sum(flot)), float(np.sum(bub))


def size_distribution_summary(m_bins: np.ndarray, M_zone: float) -> dict:
    tot = float(np.sum(np.maximum(m_bins, 0)))
    return {"r_um": (R_BINS * 1e6).tolist(),
            "mass_ppm": (np.maximum(m_bins, 0) / max(M_zone, 1.0) * 1e6).tolist(),
            "total_ppm": tot / max(M_zone, 1.0) * 1e6,
            "oxygen_in_inclusions_ppm": tot * O_FRAC_AL2O3 / max(M_zone, 1.0) * 1e6}
