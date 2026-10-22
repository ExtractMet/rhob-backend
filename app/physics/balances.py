"""Elemental and energy closure across ALL reservoirs (docs/MODEL_EQUATIONS.md section 8).

Element E inventory at time t:
   steel zones (dissolved + Fe balance) + ladle slag oxides + suspended inclusions
 + jet FeO pool + undissolved additions + vessel/duct gas + cumulative exhausted off-gas
 + cumulative skull (FeO, Al2O3) + cumulative yield losses at charge
must equal
   initial inventory + cumulative gas input (O2, leak air, vent gas) + additions charged.
Argon is closed separately (gas + exhausted + bypass = initial + input).

Energy (system = steel zones + slag + refractory walls; gases quasi-steady):
   E_stored(t) - E_stored(0) = sum(source ledger) - sum(sink ledger)
Residuals are recorded every record step (absolute and relative). A run whose residual
exceeds SolverConfig tolerances is NOT reported as successful.
"""
from __future__ import annotations

import numpy as np

from .cleanliness import O_FRAC_AL2O3
from .properties import ADDITION_MATERIALS, GAS_SPECIES, MW, SLAG_OXIDES, SPECIES
from .state_vector import ENERGY_TERMS, SINK_TERMS, SOURCE_TERMS
from .stoichiometry import ELEMENTS, add, gas_element_mass, material_element_mass, oxide_element_mass

AL_FRAC_AL2O3 = 2 * MW["Al"] / MW["Al2O3"]


def element_inventory(model, y) -> dict:
    L = model.L
    inv = {e: 0.0 for e in ELEMENTS}
    for z in model.zones:
        Mz = y[L[f"M_{z}"]]
        mz = y[L[f"m_{z}"]]
        for k, s in enumerate(SPECIES):
            inv[s] += mz[k]
        inv["Fe"] += Mz - float(np.sum(mz))
        incz = float(np.sum(y[L[f"inc_{z}"]]))
        inv["Al"] += incz * AL_FRAC_AL2O3
        inv["O"] += incz * O_FRAC_AL2O3
    for j, ox in enumerate(SLAG_OXIDES):
        add(inv, oxide_element_mass(ox, y[L["slag"].start + j]))
    add(inv, oxide_element_mass("FeO", y[L["feo_pool"]]))
    add(inv, oxide_element_mass("FeO", y[L["acc_skull"].start]))
    add(inv, oxide_element_mass("Al2O3", y[L["acc_skull"].start + 1]))
    for j, mat in enumerate(model.materials):
        add(inv, material_element_mass(mat, y[L["add"].start + j]))
    for k, g in enumerate(GAS_SPECIES):
        add(inv, gas_element_mass(g, y[L["gas"].start + k]))
        add(inv, gas_element_mass(g, y[L["acc_exh"].start + k]))
    add(inv, model.loss_reservoir)
    return inv


def element_inputs(model, y) -> dict:
    L = model.L
    inp = {e: 0.0 for e in ELEMENTS}
    for k, g in enumerate(GAS_SPECIES):
        add(inp, gas_element_mass(g, y[L["acc_in"].start + k]))
    add(inp, model.charged)
    return inp


def argon_balance(model, y, y0) -> float:
    L = model.L
    ia = GAS_SPECIES.index("Ar")
    have = y[L["gas"].start + ia] + y[L["acc_exh"].start + ia] + y[L["acc_bypass_ar"]]
    should = y0[L["gas"].start + ia] + y[L["acc_in"].start + ia]
    return float(have - should)


def stored_energy(model, y) -> float:
    L = model.L
    E = 0.0
    for z in model.zones:
        E += y[L[f"H_{z}"]]
    E += y[L["H_slag"]]
    E += model.wall_l.stored_energy(y[L["Tw_ladle"]])
    E += model.wall_vl.stored_energy(y[L["Tw_vlow"]])
    E += model.wall_vu.stored_energy(y[L["Tw_vup"]])
    return float(E)


def ledger_net(model, y) -> float:
    L = model.L
    acc = y[L["acc_E"]]
    src = sum(acc[ENERGY_TERMS.index(k)] for k in SOURCE_TERMS)
    snk = sum(acc[ENERGY_TERMS.index(k)] for k in SINK_TERMS)
    return float(src - snk)


class ClosureTracker:
    def __init__(self, model):
        self.model = model
        self.y0 = model.y.copy()
        self.inv0 = element_inventory(model, self.y0)
        self.E0 = stored_energy(model, self.y0)
        self.max_rel_mass = 0.0
        self.max_rel_energy = 0.0
        self.worst_element = None
        self.history = []

    def evaluate(self, t, y) -> dict:
        m = self.model
        inv = element_inventory(m, y)
        inp = element_inputs(m, y)
        res = {}
        rel = {}
        for e in ELEMENTS:
            should = self.inv0[e] + inp[e]
            r = inv[e] - should
            res[e] = r
            scale = max(abs(should), 1e-3)
            rel[e] = abs(r) / scale
        worst = max(rel, key=rel.get)
        Es = stored_energy(m, y)
        net = ledger_net(m, y)
        rE = (Es - self.E0) - net
        scaleE = max(abs(self.E0), 1.0)
        relE = abs(rE) / scaleE
        # relative-to-throughput metric for energy (more stringent: vs total exchanged)
        acc = y[m.L["acc_E"]]
        through = float(np.sum(np.abs(acc[: len(ENERGY_TERMS) - 5]))) + 1.0
        relE_through = abs(rE) / through
        ar = argon_balance(m, y, self.y0)
        self.max_rel_mass = max(self.max_rel_mass, rel[worst])
        self.max_rel_energy = max(self.max_rel_energy, relE)
        if self.max_rel_mass == rel[worst]:
            self.worst_element = worst
        out = {"mass_balance_relative_error": rel[worst], "mass_balance_worst_element": worst,
               "energy_balance_residual_MJ": rE / 1e6, "energy_balance_relative_error": relE,
               "energy_residual_vs_throughput": relE_through, "argon_balance_residual_mol": ar,
               "element_residual_kg": {k: float(v) for k, v in res.items()},
               "E_stored_change_MJ": (Es - self.E0) / 1e6, "E_ledger_net_MJ": net / 1e6}
        self.history.append((t, rel[worst], relE))
        return out

    def rebase(self, y) -> dict:
        """Account for an EXTERNAL state correction (lab assimilation): the difference between
        the corrected inventory and the balance expectation is booked as an explicit
        'assimilation correction' ledger line and the baseline is shifted, so closure checks
        keep measuring numerical integrity only."""
        m = self.model
        inv = element_inventory(m, y)
        inp = element_inputs(m, y)
        corr = {e: inv[e] - (self.inv0[e] + inp[e]) for e in ELEMENTS}
        for e in ELEMENTS:
            self.inv0[e] += corr[e]
        Es = stored_energy(m, y)
        net = ledger_net(m, y)
        cE = (Es - self.E0) - net
        self.E0 += cE
        self.corrections = getattr(self, "corrections", [])
        self.corrections.append({"mass_kg": {k: float(v) for k, v in corr.items() if abs(v) > 1e-9}, "energy_J": float(cE)})
        return self.corrections[-1]

    @property
    def ok(self) -> bool:
        s = self.model.scfg
        return self.max_rel_mass <= s.mass_residual_tol and self.max_rel_energy <= s.energy_residual_tol

    def message(self) -> str:
        return (f"max relative element residual {self.max_rel_mass:.2e} ({self.worst_element}); "
                f"max relative energy residual {self.max_rel_energy:.2e}")

    def element_ledger(self, y) -> dict:
        """Full per-reservoir element table for reports (kg)."""
        m = self.model
        L = m.L
        rows = {}

        def put(name, d):
            rows[name] = {e: float(d.get(e, 0.0)) for e in ELEMENTS}

        steel = {e: 0.0 for e in ELEMENTS}
        for z in m.zones:
            mz = y[L[f"m_{z}"]]
            for k, s in enumerate(SPECIES):
                steel[s] += mz[k]
            steel["Fe"] += y[L[f"M_{z}"]] - float(np.sum(mz))
        put("steel (all zones)", steel)
        sl = {}
        for j, ox in enumerate(SLAG_OXIDES):
            add(sl, oxide_element_mass(ox, y[L["slag"].start + j]))
        put("ladle slag", sl)
        inc = {}
        for z in m.zones:
            tot = float(np.sum(y[L[f"inc_{z}"]]))
            add(inc, {"Al": tot * AL_FRAC_AL2O3, "O": tot * O_FRAC_AL2O3})
        put("suspended inclusions", inc)
        put("jet FeO pool", oxide_element_mass("FeO", y[L["feo_pool"]]))
        sk = {}
        add(sk, oxide_element_mass("FeO", y[L["acc_skull"].start]))
        add(sk, oxide_element_mass("Al2O3", y[L["acc_skull"].start + 1]))
        put("vessel skull / surface slag", sk)
        ad = {}
        for j, mat in enumerate(m.materials):
            add(ad, material_element_mass(mat, y[L["add"].start + j]))
        put("undissolved additions", ad)
        gv = {}
        ge = {}
        gi = {}
        for k, g in enumerate(GAS_SPECIES):
            add(gv, gas_element_mass(g, y[L["gas"].start + k]))
            add(ge, gas_element_mass(g, y[L["acc_exh"].start + k]))
            add(gi, gas_element_mass(g, y[L["acc_in"].start + k]))
        put("vessel gas", gv)
        put("off-gas exhausted (cum.)", ge)
        put("addition yield losses (cum.)", m.loss_reservoir)
        put("INPUT: gases (O2, leak, vent)", gi)
        put("INPUT: additions charged", m.charged)
        put("INITIAL inventory", self.inv0)
        return rows
