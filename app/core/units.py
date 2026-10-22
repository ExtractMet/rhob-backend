"""Unit conversions used by the RH-OB twin.

Internal SI convention (see docs/MODEL_EQUATIONS.md section 1):
    mass kg, length m, time s, pressure Pa (ABSOLUTE), temperature K,
    energy J, amount mol, composition = mass fraction (kg/kg).

Gas flows: plant meters report NORMAL volumetric flow. In this code base
"normal" (N) means 273.15 K and 101 325 Pa (DIN 1343). A normal volume is a
measure of AMOUNT of gas, never of the actual hot low-pressure volume in the
vacuum vessel. Use ``actual_m3_per_s`` to obtain the real volumetric flow at
vessel conditions.
"""
from __future__ import annotations

R_GAS = 8.314462618  # J/(mol K)  CODATA 2018
P_NORMAL = 101_325.0  # Pa
T_NORMAL = 273.15  # K
P_STD_ATM = 101_325.0  # Pa
G_ACC = 9.80665  # m/s2
SIGMA_SB = 5.670374419e-8  # W/(m2 K4)
MOLAR_VOLUME_NORMAL_M3 = R_GAS * T_NORMAL / P_NORMAL  # 0.0224140 m3/mol


def c_to_k(t_c: float) -> float:
    return t_c + 273.15


def k_to_c(t_k: float) -> float:
    return t_k - 273.15


def mbar_to_pa(p_mbar: float) -> float:
    return p_mbar * 100.0


def pa_to_mbar(p_pa: float) -> float:
    return p_pa / 100.0


def kpa_to_pa(p_kpa: float) -> float:
    return p_kpa * 1000.0


def torr_to_pa(p_torr: float) -> float:
    return p_torr * 133.322368


def gauge_to_absolute_pa(p_gauge_pa: float, p_atm_pa: float = P_STD_ATM) -> float:
    """Gauge -> absolute. Vacuum gauges reading negative gauge values are allowed."""
    p_abs = p_gauge_pa + p_atm_pa
    if p_abs < 0:
        raise ValueError(f"absolute pressure would be negative ({p_abs} Pa)")
    return p_abs


def absolute_to_gauge_pa(p_abs_pa: float, p_atm_pa: float = P_STD_ATM) -> float:
    return p_abs_pa - p_atm_pa


def nm3h_to_mol_s(q_nm3_h: float) -> float:
    """Normal m3/h (0 degC, 1 atm) -> mol/s."""
    return q_nm3_h / 3600.0 / MOLAR_VOLUME_NORMAL_M3


def mol_s_to_nm3h(n_mol_s: float) -> float:
    return n_mol_s * MOLAR_VOLUME_NORMAL_M3 * 3600.0


def nl_min_to_mol_s(q_nl_min: float) -> float:
    """Normal litre/min -> mol/s."""
    return q_nl_min / 1000.0 / 60.0 / MOLAR_VOLUME_NORMAL_M3


def mol_s_to_nl_min(n_mol_s: float) -> float:
    return n_mol_s * MOLAR_VOLUME_NORMAL_M3 * 1000.0 * 60.0


def nl_min_to_nm3h(q_nl_min: float) -> float:
    return q_nl_min * 60.0 / 1000.0


def nm3h_to_nl_min(q: float) -> float:
    return q * 1000.0 / 60.0


def actual_m3_per_s(n_mol_s: float, t_k: float, p_pa_abs: float) -> float:
    """Ideal-gas ACTUAL volumetric flow at temperature t_k and absolute pressure p."""
    if p_pa_abs <= 0:
        raise ValueError("absolute pressure must be > 0")
    return n_mol_s * R_GAS * t_k / p_pa_abs


def mass_fraction_to_ppm(w: float) -> float:
    return w * 1.0e6


def ppm_to_mass_fraction(ppm: float) -> float:
    return ppm * 1.0e-6


def mass_fraction_to_wtpct(w: float) -> float:
    return w * 100.0


def wtpct_to_mass_fraction(pct: float) -> float:
    return pct / 100.0


def kg_s_to_t_min(q: float) -> float:
    return q * 60.0 / 1000.0


def t_min_to_kg_s(q: float) -> float:
    return q * 1000.0 / 60.0


def j_to_kwh(e: float) -> float:
    return e / 3.6e6


UNIT_METADATA = {
    "K": "kelvin", "degC": "degree Celsius", "Pa_abs": "pascal (absolute)",
    "mbar_abs": "millibar (absolute)", "kPa_abs": "kilopascal (absolute)",
    "Nm3/h": "normal cubic metre per hour (0 degC, 101.325 kPa)",
    "NL/min": "normal litre per minute (0 degC, 101.325 kPa)",
    "ppm": "parts per million by mass", "wt%": "mass percent",
    "kg/s": "kilogram per second", "t/min": "tonne per minute",
    "kWh/t": "kilowatt-hour per tonne of liquid steel", "s": "second", "min": "minute",
}
