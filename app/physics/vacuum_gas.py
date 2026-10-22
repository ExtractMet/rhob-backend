"""Dynamic vacuum vessel gas phase and pump system.

Gas inventory (mol) of species i in vessel freeboard + duct/cooler volume:
    dn_i/dt = n_gen,i + n_inj,i + n_leak,i - x_i * n_exh
Pressure from the ideal gas law over two volumes at different temperatures:
    P = n_tot R / (V_free/T_g + V_duct/T_duct)
V_free = V_vessel_internal - V_steel_in_vessel changes with the lifted steel.

Pump: capacity curve W_air(P) [kg/h dry-air equivalent] (ejector data sheets are given in
this form). Molar capacity for a gas of mean molar mass M uses the HEI molecular-weight
entrainment ratio (~ sqrt(M/29) on a mass basis):
    n_max = W_air(P)/3600 / M_air * sqrt(M_air/M)            [mol/s]
The pressure controller (pump staging/bleed valve) throttles smoothly:
    u = 0.5 [1 + tanh((P - P_sp)/(band*P_sp + 5 Pa))]
so the exhaust never acts below the set-point and the attainable vacuum is decided by
pump capacity vs gas load (CO surges during OB raise pressure physically).
The actual volumetric speed at suction conditions is reported as S = n R T_suct / P.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.units import R_GAS
from .properties import GAS_SPECIES, MW

M_AIR = 28.96e-3


class PumpCurve:
    def __init__(self, curve: list[list[float]]):
        arr = np.array(sorted(curve, key=lambda r: r[0]), dtype=float)
        if arr.shape[0] < 2 or np.any(arr[:, 0] <= 0):
            raise ValueError("pump curve needs >= 2 points with P > 0")
        self.logp = np.log(arr[:, 0])
        self.w = arr[:, 1]
        self.p_ult = float(arr[0, 0]) if arr[0, 1] <= 0 else 0.0

    def w_air_kg_h(self, p: float) -> float:
        if p <= 0:
            return 0.0
        return float(np.interp(math.log(p), self.logp, self.w))


def mean_molar_mass(n: np.ndarray) -> float:
    tot = float(np.sum(np.maximum(n, 0.0)))
    if tot <= 0:
        return M_AIR
    return float(sum(max(n[i], 0.0) * MW[g] for i, g in enumerate(GAS_SPECIES)) / tot)


def molar_capacity(curve: PumpCurve, p: float, M_gas: float, health: float) -> float:
    w = curve.w_air_kg_h(p) * health
    return w / 3600.0 / M_AIR * math.sqrt(M_AIR / max(M_gas, 1e-3))


def throttle(p: float, p_sp: float, band_frac: float) -> float:
    return 0.5 * (1.0 + math.tanh((p - p_sp) / (band_frac * p_sp + 5.0)))


def pressure(n_tot: float, V_free: float, T_g: float, V_duct: float, T_duct: float) -> float:
    return n_tot * R_GAS / (V_free / T_g + V_duct / T_duct)


def initial_moles(p: float, V_free: float, T_g: float, V_duct: float, T_duct: float) -> float:
    return p * (V_free / T_g + V_duct / T_duct) / R_GAS


def leak_mol_s(leak_kg_h: float) -> tuple[float, float]:
    """Air in-leakage split into (N2, O2) mol/s (Ar in air lumped into N2)."""
    n_air = leak_kg_h / 3600.0 / M_AIR
    return 0.79 * n_air, 0.21 * n_air


def steam_kg(gas_kg: float, steam_ratio: float) -> float:
    return gas_kg * steam_ratio
