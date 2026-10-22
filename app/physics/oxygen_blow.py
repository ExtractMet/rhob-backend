"""RH-OB oxygen-blowing module (submerged tuyeres in the lower vacuum vessel).

Elemental-O accounting (mol O2/s injected  ->  sinks), no fixed unexplained split:

  1. Absorption in the bath plume: eta_abs = 1 - exp(-lambda * h_sub), h_sub = depth of
     steel above the tuyere axis. Unabsorbed "slip" O2 reaches the freeboard.
  2. Jet-interface competitive oxidation. The O-potential at the jet interface is high
     (FeO-saturated), so every solute reaching the interface is oxidized; solute supply
     is transport limited:  n_i,max = (rho kA_jet) * [%i]/100 / M_i  (mol/s).
     Absorbed O is consumed in the order of thermodynamic affinity (Al > Ti > Si > C >
     Mn > Fe) up to each transport limit; the remainder oxidizes Fe to FeO (solvent,
     unlimited supply).  Direct C oxidation produces CO at the jet.
  3. Jet FeO enters a "FeO pool" that dissolves into the bath (FeO -> Fe + [O]) at a rate
     proportional to (1 - [O]/[O]_sat); a small fraction is lost to skull/slag.
  4. Slip O2 in the freeboard: a fraction burns CO -> CO2 (post-combustion, limited by
     available CO), the rest leaves with the off-gas (measured by the O2 analyzer).

Energetics follow Hess's law via 1/2 O2 -> [O] (T1) + oxide formation from [O] - see
solver.py; nothing here adds heat by assumption.  Aluminium chemical heating is NOT
automatic: it only occurs if the user schedules Al together with O2 AND
PlantConfig.chemical_heating_enabled is True (otherwise the guard rejects the phase).
"""
from __future__ import annotations

import math

from .properties import MW

# affinity order at the jet interface (most stable oxide first); O atoms per element atom
JET_ORDER = [("Al", 1.5), ("Ti", 2.0), ("Si", 2.0), ("C", 1.0), ("Mn", 1.0)]
# Mn competes with the solvent Fe for the residual jet oxygen: the interfacial oxide is a
# FeO-MnO melt with (X_MnO/X_FeO) ~ K_MnFe [%Mn] (Mn + FeO = MnO + Fe; K_MnFe ~ 3 per wt%
# at 1873 K, Turkdogan 1996, ILLUSTRATIVE). Mn therefore takes the fraction
# K[%Mn]/(1+K[%Mn]) of the residual O, bounded by its transport supply.
K_MN_FE = 3.0


def absorption_efficiency(lam: float, h_sub: float) -> float:
    return 1.0 - math.exp(-lam * max(h_sub, 0.0))


def jet_partition(n_O_abs: float, wt: dict, rho: float, kA: float) -> dict:
    """Allocate absorbed atomic O [mol O/s] among solutes and Fe.

    wt: bulk vessel composition in wt%. Returns mol/s of element oxidized per species and
    mol/s of FeO formed.
    """
    res = {k: 0.0 for k, _ in JET_ORDER}
    res["FeO"] = 0.0
    remaining = max(n_O_abs, 0.0)
    for el, o_per in JET_ORDER:
        if remaining <= 0:
            break
        supply = rho * kA * max(wt.get(el, 0.0), 0.0) / 100.0 / MW[el]  # mol el/s
        if el == "Mn":
            x = K_MN_FE * max(wt.get("Mn", 0.0), 0.0)
            n_el = min(supply, remaining * x / (1.0 + x))
        else:
            n_el = min(supply, remaining / o_per)
        res[el] = n_el
        remaining -= n_el * o_per
    res["FeO"] = remaining  # mol FeO/s (1 O each)
    return res


def feo_dissolution_rate(m_feo_pool: float, k_diss: float, O_pct: float, O_sat_pct: float) -> float:
    """kg FeO/s dissolving as Fe + [O]."""
    if m_feo_pool <= 0:
        return 0.0
    drive = max(1.0 - O_pct / max(O_sat_pct, 1e-6), 0.0)
    return k_diss * m_feo_pool * drive


def post_combustion(n_o2_slip: float, n_co_available: float, frac: float) -> tuple[float, float]:
    """Returns (mol CO burnt/s, mol O2 consumed/s)."""
    n_o2_pc = min(frac * n_o2_slip, 0.5 * max(n_co_available, 0.0))
    return 2.0 * n_o2_pc, n_o2_pc
