"""Stoichiometric bookkeeping: element content of every reservoir.

Used by balances.py to prove elemental closure across steel zones, slag, inclusions,
FeO pool, undissolved additions, vessel gas, exhausted off-gas, skull and yield losses.
"""
from __future__ import annotations

from .properties import ADDITION_MATERIALS, GAS_ELEMENTS, GAS_SPECIES, MW, OXIDE_ELEMENTS, SLAG_OXIDES, SPECIES

ELEMENTS = ["Fe", "C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "S", "P", "Cr", "Ni", "Nb", "V", "Cu", "Mo", "Ca", "Mg"]


def oxide_element_mass(oxide: str, mass: float) -> dict:
    el, n_el, n_o = OXIDE_ELEMENTS[oxide]
    mol = mass / MW[oxide]
    return {el: mol * n_el * MW[el], "O": mol * n_o * MW["O"]}


def gas_element_mass(species: str, mol: float) -> dict:
    return {el: mol * n * MW[el] for el, n in GAS_ELEMENTS[species].items()}


def material_element_mass(material: str, mass: float) -> dict:
    return {el: mass * frac for el, frac in ADDITION_MATERIALS[material]["comp"].items()}


def add(acc: dict, d: dict, sign: float = 1.0):
    for k, v in d.items():
        acc[k] = acc.get(k, 0.0) + sign * v


def check_reaction_balance(reactants: dict, products: dict) -> dict:
    """Element balance of a reaction given as {species: stoich}. Species may be elements,
    gases or oxides. Returns residual atoms per element (should all be 0)."""
    def atoms(sp):
        if sp in GAS_ELEMENTS:
            return dict(GAS_ELEMENTS[sp])
        if sp in OXIDE_ELEMENTS:
            el, n_el, n_o = OXIDE_ELEMENTS[sp]
            return {el: n_el, "O": n_o}
        return {sp: 1}
    res: dict = {}
    for sp, nu in reactants.items():
        for el, n in atoms(sp).items():
            res[el] = res.get(el, 0) + nu * n
    for sp, nu in products.items():
        for el, n in atoms(sp).items():
            res[el] = res.get(el, 0) - nu * n
    return res


REACTION_SET = {
    "C+O=CO": ({"C": 1, "O": 1}, {"CO": 1}),
    "2C+O2=2CO": ({"C": 2, "O2": 1}, {"CO": 2}),
    "2Al+3O=Al2O3": ({"Al": 2, "O": 3}, {"Al2O3": 1}),
    "Si+2O=SiO2": ({"Si": 1, "O": 2}, {"SiO2": 1}),
    "Mn+O=MnO": ({"Mn": 1, "O": 1}, {"MnO": 1}),
    "Ti+2O=TiO2": ({"Ti": 1, "O": 2}, {"TiO2": 1}),
    "Fe+O=FeO": ({"Fe": 1, "O": 1}, {"FeO": 1}),
    "CO+1/2O2=CO2": ({"CO": 1, "O2": 0.5}, {"CO2": 1}),
    "2H=H2": ({"H": 2}, {"H2": 1}),
    "2N=N2": ({"N": 2}, {"N2": 1}),
}
