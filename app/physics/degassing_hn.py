"""Hydrogen and nitrogen removal (and pick-up) at the vessel free surface and Ar bubbles.

Hydrogen: Sieverts' law  [%H]_eq = K_H sqrt(p_H2/atm) / f_H ; the surface reaction is fast,
so the rate is liquid-side mass-transfer controlled (first order):
    J_H [kg/s] = rho k_H A ([%H] - [%H]_eq)/100

Nitrogen: mixed control by liquid mass transfer and a SECOND-ORDER interfacial
dissociation/recombination step poisoned by surface-active O and S
(rate law of the Ban-ya / Fruehan type):
    J_N2 [mol/m2 s] = k_r (p_N2,i - p_N2,gas),  p_N2,i = (f_N [%N]_i / K_N)^2 atm
    k_r = k_r0 / (1 + K_O a_O + K_S a_S)^2
    beta ([%N] - [%N]_i) = 2 J_N2 * 100 M_N / rho ...  -> quadratic in [%N]_i.
Hence H and N degas DIFFERENTLY: N removal stalls in high-O / high-S steel and becomes
infeasible for very low targets, which the endpoint checker reports.
Air leaks / N2 vent raise p_N2 and give pick-up (negative removal) - reversible law.
"""
from __future__ import annotations

import math

from .properties import MW
from .thermodynamics import log10K


def hydrogen_surface_rate(H_pct, T, p_h2_gas_pa, fH, rho, kH, A) -> float:
    """kg H/s removed (negative = absorbed)."""
    KH = 10.0 ** log10K("H2_H", T)
    H_eq = KH * math.sqrt(max(p_h2_gas_pa, 0.0) / 101_325.0) / fH
    return rho * kH * A * (H_pct - H_eq) / 100.0


def nitrogen_kr(kin, O_pct, S_pct, fO=1.0, fS=1.0) -> float:
    aO = max(O_pct, 0) * fO
    aS = max(S_pct, 0) * fS
    return kin.k_r0_N_mol_m2_s_atm / (1.0 + kin.K_O_poison * aO + kin.K_S_poison * aS) ** 2


def nitrogen_surface_rate(N_pct, T, p_n2_gas_pa, fN, rho, kN, A, kr) -> tuple[float, float]:
    """Returns (kg N/s removed (neg = pick-up), interface [%N]_i)."""
    if A <= 0:
        return 0.0, N_pct
    KN = 10.0 ** log10K("N2_N", T)
    p_gas = max(p_n2_gas_pa, 0.0) / 101_325.0
    beta = rho * kN / (100.0 * MW["N"])  # mol N/(m2 s) per wt%
    a = 2.0 * kr * (fN / KN) ** 2
    b = beta
    c = -(beta * N_pct + 2.0 * kr * p_gas)
    if a <= 0:
        Ni = N_pct
    else:
        Ni = (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)
    flux_mol_N = beta * (N_pct - Ni)  # mol N/(m2 s)
    return flux_mol_N * A * MW["N"], Ni


def nitrogen_bubble_peq_effective(N_pct, T, fN, kr, kr0) -> float:
    """Equilibrium N2 pressure in Ar bubbles scaled by the kinetic poisoning ratio kr/kr0
    (bubbles have short residence; a poisoned interface cannot approach equilibrium)."""
    KN = 10.0 ** log10K("N2_N", T)
    p_eq = (fN * max(N_pct, 0.0) / KN) ** 2 * 101_325.0
    return p_eq * (kr / kr0 if kr0 > 0 else 0.0)
