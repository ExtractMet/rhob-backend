"""Chemical thermodynamics of dilute liquid-iron solutions (1 wt% standard state).

Equilibrium constants are written log10 K = A/T + B for the reactions listed in
REACTIONS; enthalpies follow from the van 't Hoff relation, dH = -2.303 R A, so the
heat released by each reaction is CONSISTENT with its equilibrium constant.

Sources (docs/SOURCES.md):
  T1  Sigworth G.K., Elliott J.F., "The thermodynamics of liquid dilute iron alloys",
      Metal Science 8 (1974) 298-310.   (solution free energies, interaction coeffs)
  T2  Turkdogan E.T., Fundamentals of Steelmaking, The Institute of Materials (1996).
  T3  Japan Society for the Promotion of Science (19th Committee), Steelmaking Data
      Sourcebook, Gordon & Breach (1988).
The values are widely-used literature values intended for an ENGINEERING DEMO. A plant
deployment must replace them with its adopted thermochemical database (e.g. FactSage /
Thermo-Calc derived) and record the change in config/thermo_sources.yaml.
"""
from __future__ import annotations

import math

import numpy as np

from .properties import SPECIES, SPECIES_INDEX
from ..core.units import R_GAS

LN10 = math.log(10.0)

# log10 K = A/T + B ; K defined with activities on 1 wt% (henrian) basis, pressures in atm,
# pure oxide / FeO(l) activity relative to pure substance.
REACTIONS = {
    # [C] + [O] = CO(g)          K = pCO / (aC aO)
    "C_O_CO": {"A": 1160.0, "B": 2.003, "src": "T2/T3"},
    # 1/2 O2(g) = [O]           K = aO / pO2^0.5   (dG = -117110 - 3.39 T)
    "O2_O": {"A": 117110.0 / (R_GAS * LN10), "B": 3.39 / (R_GAS * LN10), "src": "T1"},
    # 2[Al] + 3[O] = Al2O3(s)   K = 1/(aAl^2 aO^3)  (dG = -1 202 000 + 386.3 T)
    "Al_deox": {"A": 1_202_000.0 / (R_GAS * LN10), "B": -386.3 / (R_GAS * LN10), "src": "T2"},
    # [Si] + 2[O] = SiO2(s)     K = aSiO2/(aSi aO^2)
    "Si_deox": {"A": 30410.0, "B": -11.59, "src": "T2"},
    # [Mn] + [O] = MnO(s)       K = aMnO/(aMn aO)
    "Mn_deox": {"A": 14450.0, "B": -6.43, "src": "T2"},
    # [Ti] + 2[O] = TiO2(s)     dG = -675 580 + 229.4 T (Hess: Ti/TiO2 pure data + T1)
    "Ti_deox": {"A": 675_580.0 / (R_GAS * LN10), "B": -229.4 / (R_GAS * LN10), "src": "derived T1/T2"},
    # Fe(l) + [O] = FeO(l)      K = aFeO/aO
    "FeO_O": {"A": 6150.0, "B": -2.604, "src": "T2"},
    # 1/2 H2(g) = [H]   Sieverts: log[%H] = -1905/T - 1.591 + 0.5 log pH2
    "H2_H": {"A": -1905.0, "B": -1.591, "src": "T1"},
    # 1/2 N2(g) = [N]   Sieverts: log[%N] = -188/T - 1.246 + 0.5 log pN2
    "N2_N": {"A": -188.0, "B": -1.246, "src": "T1"},
}

# Reaction enthalpies [J per mol of the reaction as written] from van 't Hoff
DH = {k: -LN10 * R_GAS * v["A"] for k, v in REACTIONS.items()}
DH_CO_POSTCOMB = -283_000.0  # CO + 1/2 O2 = CO2 (gas), J/mol CO, T2


def log10K(name: str, T: float) -> float:
    r = REACTIONS[name]
    return r["A"] / T + r["B"]


def K(name: str, T: float) -> float:
    return 10.0 ** log10K(name, T)


def delta_G(name: str, T: float) -> float:
    """Standard Gibbs energy [J/mol] = -R T ln K."""
    return -R_GAS * T * LN10 * log10K(name, T)


# ----------------------------------------------------------------------------------
# Wagner first-order interaction parameters e_i^j (wt% basis), T1/T3 (1873 K values)
# Only species in SPECIES are used; missing pairs = 0.
# ----------------------------------------------------------------------------------
_E = {
    "C": {"C": 0.14, "O": -0.34, "Si": 0.08, "Mn": -0.012, "Al": 0.043, "S": 0.046, "Cr": -0.024,
          "Ni": 0.012, "N": 0.11, "H": 0.67, "P": 0.051},
    "O": {"O": -0.20, "C": -0.45, "Al": -3.9, "Si": -0.131, "Mn": -0.021, "S": -0.133, "Cr": -0.04,
          "Ni": 0.006, "Ti": -0.6, "N": 0.057, "H": -3.1, "P": 0.07, "V": -0.3, "Nb": -0.14, "Cu": -0.013, "Mo": 0.0035},
    "Al": {"Al": 0.045, "O": -6.6, "C": 0.091, "Si": 0.0056, "N": -0.058, "S": 0.030, "Mn": 0.0},
    "Si": {"Si": 0.11, "O": -0.23, "C": 0.18, "Al": 0.058, "Mn": 0.002, "S": 0.056, "N": 0.09},
    "Mn": {"Mn": 0.0, "O": -0.083, "C": -0.07, "S": -0.048, "Si": -0.0002},
    "Ti": {"Ti": 0.013, "O": -1.8, "C": -0.165, "N": -1.8, "S": -0.11, "Al": 0.0},
    "H": {"C": 0.06, "O": -0.19, "Si": 0.027, "Mn": -0.0014, "Al": 0.013, "Cr": -0.0022,
          "Ni": 0.0, "S": 0.008, "Ti": -0.019, "Nb": -0.0023, "V": -0.0074, "P": 0.011},
    "N": {"C": 0.13, "O": 0.05, "Si": 0.047, "Mn": -0.02, "Al": -0.028, "Cr": -0.047, "Ni": 0.01,
          "S": 0.007, "Ti": -0.53, "Nb": -0.06, "V": -0.093, "P": 0.045, "Cu": 0.009, "Mo": -0.011},
    "S": {"S": -0.028, "C": 0.11, "O": -0.27, "Si": 0.063, "Mn": -0.026, "Al": 0.035},
}

E_MATRIX = np.zeros((len(SPECIES), len(SPECIES)))
for _i, _row in _E.items():
    for _j, _val in _row.items():
        E_MATRIX[SPECIES_INDEX[_i], SPECIES_INDEX[_j]] = _val


def activity_coefficients(wtpct: np.ndarray) -> np.ndarray:
    """Henrian activity coefficients f_i (1 wt% standard state), first-order Wagner.

    log10 f_i = sum_j e_i^j [%j].  The exponent is bounded to |log f| <= 3 to keep the
    first-order formalism inside a physically sensible range; any bounding is flagged by
    ``activity_bounded`` so callers can raise a validity warning (no silent clipping).
    """
    lf = E_MATRIX @ np.maximum(wtpct, 0.0)
    return 10.0 ** np.clip(lf, -3.0, 3.0)


def activity_bounded(wtpct: np.ndarray) -> bool:
    lf = E_MATRIX @ np.maximum(wtpct, 0.0)
    return bool(np.any(np.abs(lf) > 3.0))


# ----------------------------------------------------------------------------------
# Equilibrium helpers (wt%)
# ----------------------------------------------------------------------------------
def co_equilibrium_product(T: float, p_co_pa: float, fC: float, fO: float) -> float:
    """m = [%C][%O] at equilibrium with p_CO [Pa]."""
    return (p_co_pa / 101_325.0) / (K("C_O_CO", T) * fC * fO)


def p_co_equilibrium_pa(T: float, c_pct: float, o_pct: float, fC: float, fO: float) -> float:
    return K("C_O_CO", T) * fC * c_pct * fO * o_pct * 101_325.0


def o_eq_al(T: float, al_pct: float, fAl: float, fO: float, a_al2o3: float = 1.0) -> float:
    """Dissolved [%O] in equilibrium with [%Al] and Al2O3 activity."""
    al = max(al_pct * fAl, 1e-9)
    return (a_al2o3 / (K("Al_deox", T) * al * al)) ** (1.0 / 3.0) / fO


def o_eq_si(T: float, si_pct: float, fSi: float, fO: float, a_sio2: float = 1.0) -> float:
    si = max(si_pct * fSi, 1e-9)
    return math.sqrt(a_sio2 / (K("Si_deox", T) * si)) / fO


def o_eq_mn(T: float, mn_pct: float, fMn: float, fO: float, a_mno: float = 1.0) -> float:
    mn = max(mn_pct * fMn, 1e-9)
    return a_mno / (K("Mn_deox", T) * mn) / fO


def o_eq_ti(T: float, ti_pct: float, fTi: float, fO: float, a_tio2: float = 1.0) -> float:
    ti = max(ti_pct * fTi, 1e-9)
    return math.sqrt(a_tio2 / (K("Ti_deox", T) * ti)) / fO


def o_saturation_feo(T: float, fO: float, a_feo: float = 1.0) -> float:
    """[%O] at saturation with liquid FeO (a_FeO = 1)."""
    return a_feo / (K("FeO_O", T) * fO)


def h_sieverts_pct(T: float, p_h2_pa: float, fH: float) -> float:
    return 10.0 ** log10K("H2_H", T) * math.sqrt(max(p_h2_pa, 0.0) / 101_325.0) / fH


def n_sieverts_pct(T: float, p_n2_pa: float, fN: float) -> float:
    return 10.0 ** log10K("N2_N", T) * math.sqrt(max(p_n2_pa, 0.0) / 101_325.0) / fN


def p_h2_eq_pa(T: float, h_pct: float, fH: float) -> float:
    k = 10.0 ** log10K("H2_H", T)
    return (fH * max(h_pct, 0.0) / k) ** 2 * 101_325.0


def p_n2_eq_pa(T: float, n_pct: float, fN: float) -> float:
    k = 10.0 ** log10K("N2_N", T)
    return (fN * max(n_pct, 0.0) / k) ** 2 * 101_325.0


def thermo_table(T: float) -> dict:
    """Snapshot table for display / documentation (values at T)."""
    out = {}
    for name, r in REACTIONS.items():
        out[name] = {"log10K": log10K(name, T), "dG_J_per_mol": delta_G(name, T),
                     "dH_J_per_mol": DH[name], "A": r["A"], "B": r["B"], "source": r["src"]}
    return out
