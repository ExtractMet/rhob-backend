"""Physical properties: molar masses, steel / slag / gas heat capacities, enthalpy model,
refractory property library.

All values are textbook-level property data (see docs/SOURCES.md, items P1-P5).
Values labelled ILLUSTRATIVE are demonstration defaults that a plant must replace with
supplier data sheets (refractory) or its own thermochemical database.
"""
from __future__ import annotations

import numpy as np

# ----------------------------------------------------------------------------------
# Molar masses  [kg/mol]   (IUPAC 2021 standard atomic weights, rounded)
# ----------------------------------------------------------------------------------
MW = {
    "Fe": 55.845e-3, "C": 12.011e-3, "O": 15.999e-3, "H": 1.008e-3, "N": 14.007e-3,
    "Al": 26.982e-3, "Si": 28.085e-3, "Mn": 54.938e-3, "Ti": 47.867e-3, "S": 32.06e-3,
    "P": 30.974e-3, "Cr": 51.996e-3, "Ni": 58.693e-3, "Nb": 92.906e-3, "V": 50.942e-3,
    "Cu": 63.546e-3, "Mo": 95.95e-3, "Ar": 39.948e-3, "Ca": 40.078e-3, "Mg": 24.305e-3,
}
MW["CO"] = MW["C"] + MW["O"]
MW["CO2"] = MW["C"] + 2 * MW["O"]
MW["O2"] = 2 * MW["O"]
MW["N2"] = 2 * MW["N"]
MW["H2"] = 2 * MW["H"]
MW["FeO"] = MW["Fe"] + MW["O"]
MW["MnO"] = MW["Mn"] + MW["O"]
MW["SiO2"] = MW["Si"] + 2 * MW["O"]
MW["Al2O3"] = 2 * MW["Al"] + 3 * MW["O"]
MW["CaO"] = MW["Ca"] + MW["O"]
MW["MgO"] = MW["Mg"] + MW["O"]
MW["TiO2"] = MW["Ti"] + 2 * MW["O"]

# Dissolved species tracked in the steel zones. Fe is the balance (solvent).
SPECIES = ["C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "S", "P", "Cr", "Ni", "Nb", "V", "Cu", "Mo"]
REACTIVE = ["C", "O", "H", "N", "Al", "Si", "Mn", "Ti"]
PASSIVE = [s for s in SPECIES if s not in REACTIVE]
SPECIES_INDEX = {s: i for i, s in enumerate(SPECIES)}

SLAG_OXIDES = ["FeO", "MnO", "SiO2", "Al2O3", "CaO", "MgO", "TiO2"]
# element -> (oxide, atoms of element per oxide, O atoms per oxide)
OXIDE_OF = {
    "Fe": ("FeO", 1, 1), "Mn": ("MnO", 1, 1), "Si": ("SiO2", 1, 2), "Al": ("Al2O3", 2, 3),
    "Ca": ("CaO", 1, 1), "Mg": ("MgO", 1, 1), "Ti": ("TiO2", 1, 2),
}
OXIDE_ELEMENTS = {ox: (el, n_el, n_o) for el, (ox, n_el, n_o) in OXIDE_OF.items()}

GAS_SPECIES = ["Ar", "CO", "CO2", "O2", "N2", "H2"]
GAS_INDEX = {g: i for i, g in enumerate(GAS_SPECIES)}
# element content of gas species (atoms per molecule)
GAS_ELEMENTS = {
    "Ar": {}, "CO": {"C": 1, "O": 1}, "CO2": {"C": 1, "O": 2}, "O2": {"O": 2},
    "N2": {"N": 2}, "H2": {"H": 2},
}

# Mean molar heat capacities of gases between 298 K and ~1900 K [J/(mol K)]
# (integrated Shomate/JANAF-type averages; P2 in SOURCES.md). Used for sensible heat
# of gases leaving the bath: Q = n * cp_mean * (T - 298.15).
CP_GAS_MEAN = {"Ar": 20.79, "CO": 33.6, "CO2": 54.3, "O2": 35.4, "N2": 33.2, "H2": 31.0}

# ----------------------------------------------------------------------------------
# Liquid-steel enthalpy model
# ----------------------------------------------------------------------------------
# Reference: solid steel at 298.15 K has h = 0.
# h_liq(T) = H1800 + cp_l(w) * (T - 1800)            valid 1790 K <= T <= 2000 K
# H1800 from cp_solid(mean)=0.75 kJ/kgK over 298->1809 K plus fusion 247 kJ/kg
# (pure Fe: dH_fus = 13.81 kJ/mol). cp_l(Fe) = 46.0 J/(mol K) = 824 J/(kg K).
T_REF_LIQ = 1800.0
H1800_STEEL = 0.75e3 * (1809.0 - 298.15) + 247.0e3 - 824.0 * 9.0  # J/kg at 1800 K, liquid
CP_L_FE = 824.0
# liquid partial specific heats used in the linear mixing rule [J/(kg K)]
CP_L_ELEMENT = {"C": 1720.0, "Mn": 838.0, "Si": 1030.0, "Cr": 756.0, "Ni": 734.0,
                "Al": 1177.0, "Mo": 450.0, "Cu": 512.0, "Ti": 980.0}


def steel_cp_liquid(w: np.ndarray) -> float:
    """cp of liquid steel [J/(kg K)] from mass fractions ``w`` ordered as SPECIES."""
    cp = CP_L_FE
    tot = 0.0
    acc = 0.0
    for el, cpe in CP_L_ELEMENT.items():
        wi = w[SPECIES_INDEX[el]]
        tot += wi
        acc += wi * cpe
    return cp * (1.0 - tot) + acc


def steel_h(T: float, cp_l: float) -> float:
    return H1800_STEEL + cp_l * (T - T_REF_LIQ)


def steel_T_from_h(h: float, cp_l: float) -> float:
    return T_REF_LIQ + (h - H1800_STEEL) / cp_l


# Liquid steel density [kg/m3] (approx. 7000 at 1873 K; linear dT term from
# Jimbo & Cramb, Metall. Trans. B 24 (1993) 5-10 for Fe-C melts, simplified)
def steel_density(T: float) -> float:
    return 7030.0 - 0.88 * (T - 1873.15)


STEEL_VISCOSITY = 5.5e-3  # Pa s, liquid iron ~1873 K
STEEL_KIN_VISC = STEEL_VISCOSITY / 7000.0
SURFACE_TENSION_STEEL = 1.5  # N/m (O/S lower it; kept constant)

# ----------------------------------------------------------------------------------
# Slag
# ----------------------------------------------------------------------------------
CP_SLAG = 1250.0  # J/(kg K) mean, liquid CaO-Al2O3-SiO2 slags (ILLUSTRATIVE)
K_SLAG = 1.5  # W/(m K) effective conductivity of a liquid/semi-solid slag layer
RHO_SLAG = 2800.0

# ----------------------------------------------------------------------------------
# Refractory library (ILLUSTRATIVE typical data-sheet values; replace with supplier data)
#   k [W/(m K)], rho [kg/m3], cp [J/(kg K)], max service T [K]
# ----------------------------------------------------------------------------------
REFRACTORY_LIBRARY = {
    "MgO-C (10% C)": {"k": 9.0, "rho": 2950.0, "cp": 1050.0, "Tmax": 2073.0},
    "MgO-Cr (direct bonded)": {"k": 2.8, "rho": 3150.0, "cp": 1000.0, "Tmax": 2073.0},
    "Alumina-spinel castable": {"k": 2.4, "rho": 3000.0, "cp": 1050.0, "Tmax": 2023.0},
    "High-alumina brick (safety)": {"k": 1.8, "rho": 2600.0, "cp": 1000.0, "Tmax": 1973.0},
    "Fireclay brick": {"k": 1.2, "rho": 2200.0, "cp": 950.0, "Tmax": 1773.0},
    "Insulating board": {"k": 0.25, "rho": 900.0, "cp": 1000.0, "Tmax": 1373.0},
    "Microporous insulation": {"k": 0.05, "rho": 300.0, "cp": 900.0, "Tmax": 1273.0},
    "Steel shell": {"k": 45.0, "rho": 7850.0, "cp": 520.0, "Tmax": 723.0},
}

# Inclusion (alumina) properties
RHO_AL2O3 = 3950.0

# ----------------------------------------------------------------------------------
# Addition materials (ILLUSTRATIVE typical grades; plants supply certified analyses)
#   comp: mass fractions; Tm: liquidus/melting temperature [K]; rho kg/m3;
#   cp J/(kg K) (solid mean); L J/kg latent heat; d_m nominal lump diameter [m]
#   yield_default: fraction recovered into the bath (balance -> loss reservoir)
# ----------------------------------------------------------------------------------
ADDITION_MATERIALS = {
    "Al_shot": {"label": "Aluminium shot/ingot (99.7% Al)", "comp": {"Al": 0.997, "Fe": 0.003},
                "Tm": 933.0, "rho": 2700.0, "cp": 1000.0, "L": 397e3, "d_m": 0.020, "yield_default": 0.92},
    "FeSi75": {"label": "Ferro-silicon 75", "comp": {"Si": 0.75, "Al": 0.012, "C": 0.001, "Fe": 0.237},
               "Tm": 1590.0, "rho": 3200.0, "cp": 800.0, "L": 1.2e6, "d_m": 0.025, "yield_default": 0.90},
    "LC_FeMn": {"label": "Low-carbon ferro-manganese 80", "comp": {"Mn": 0.80, "C": 0.005, "Si": 0.01, "P": 0.002, "Fe": 0.183},
                "Tm": 1530.0, "rho": 7200.0, "cp": 700.0, "L": 2.5e5, "d_m": 0.025, "yield_default": 0.95},
    "Mn_metal": {"label": "Electrolytic manganese", "comp": {"Mn": 0.997, "Fe": 0.003},
                 "Tm": 1519.0, "rho": 7210.0, "cp": 650.0, "L": 2.35e5, "d_m": 0.015, "yield_default": 0.96},
    "FeTi70": {"label": "Ferro-titanium 70", "comp": {"Ti": 0.70, "Al": 0.03, "Fe": 0.27},
               "Tm": 1360.0, "rho": 5400.0, "cp": 650.0, "L": 3.0e5, "d_m": 0.020, "yield_default": 0.80},
    "FeNb65": {"label": "Ferro-niobium 65", "comp": {"Nb": 0.65, "Fe": 0.35},
               "Tm": 1850.0, "rho": 8000.0, "cp": 450.0, "L": 2.9e5, "d_m": 0.015, "yield_default": 0.95},
    "FeV80": {"label": "Ferro-vanadium 80", "comp": {"V": 0.80, "Fe": 0.20},
              "Tm": 1950.0, "rho": 6400.0, "cp": 520.0, "L": 3.4e5, "d_m": 0.015, "yield_default": 0.95},
    "LC_FeCr": {"label": "Low-carbon ferro-chrome", "comp": {"Cr": 0.70, "C": 0.001, "Si": 0.01, "Fe": 0.289},
                "Tm": 1880.0, "rho": 7100.0, "cp": 600.0, "L": 3.0e5, "d_m": 0.020, "yield_default": 0.97},
    "Ni_cathode": {"label": "Nickel cathode", "comp": {"Ni": 0.999, "Fe": 0.001},
                   "Tm": 1728.0, "rho": 8900.0, "cp": 520.0, "L": 2.9e5, "d_m": 0.030, "yield_default": 0.99},
    "Cu_scrap": {"label": "Copper", "comp": {"Cu": 0.999, "Fe": 0.001},
                 "Tm": 1358.0, "rho": 8900.0, "cp": 420.0, "L": 2.05e5, "d_m": 0.020, "yield_default": 0.99},
    "FeMo": {"label": "Ferro-molybdenum 65", "comp": {"Mo": 0.65, "Fe": 0.35},
             "Tm": 2030.0, "rho": 9000.0, "cp": 400.0, "L": 2.8e5, "d_m": 0.015, "yield_default": 0.97},
    "Carbon": {"label": "Low-N carburiser (graphite)", "comp": {"C": 0.98, "Fe": 0.02},
               "Tm": 4000.0, "rho": 1800.0, "cp": 1400.0, "L": 0.0, "d_m": 0.005, "yield_default": 0.85},
    "Cooling_scrap": {"label": "Clean steel scrap / pig coolant", "comp": {"C": 0.0005, "Mn": 0.002, "Fe": 0.9975},
                      "Tm": 1790.0, "rho": 7800.0, "cp": 650.0, "L": 2.7e5, "d_m": 0.050, "yield_default": 1.0},
}

# Heats of solution of pure element into 1 wt% standard state in liquid Fe [J/mol]
# (enthalpy part of Sigworth & Elliott 1974 free energies; pure element in the state noted).
# Used as reaction heat on dissolution. P3 in SOURCES.md.
H_SOLUTION = {
    "Al": -63_180.0,  # Al(l)
    "C": 22_590.0,    # C(gr)
    "Cr": 19_250.0,   # Cr(s)
    "Mn": 4_080.0,    # Mn(l)
    "Ni": -23_000.0,  # Ni(l)
    "Si": -131_500.0, # Si(l)
    "Ti": -31_200.0,  # Ti(s)
    "V": -20_710.0,   # V(s)
    "Cu": 33_470.0,   # Cu(l)
    "Mo": 27_610.0,   # Mo(s)
    "Nb": 23_000.0,   # Nb(s)  (lower confidence)
    "P": 0.0, "S": 0.0, "Fe": 0.0,
}


def comp_vector(comp: dict) -> np.ndarray:
    """Dissolved-species mass-fraction vector (SPECIES order) from a dict."""
    v = np.zeros(len(SPECIES))
    for k, val in comp.items():
        if k in SPECIES_INDEX:
            v[SPECIES_INDEX[k]] = val
    return v
