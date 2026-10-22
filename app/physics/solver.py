"""Coupled dynamic RH-OB model: right-hand side, integration, discrete events, recording.

The physical core is independent of FastAPI/Streamlit. ``RHOBModel`` integrates the state
vector (state_vector.Layout) with scipy.integrate.solve_ivp (stiff BDF by default) over
segments with piecewise-constant manipulated variables; segments are split at phase
changes, additions, samples and record times. Discrete events (immersion, withdrawal,
additions, abort) are applied between segments and are mass/energy conserving.

See docs/MODEL_EQUATIONS.md for every equation used below; section numbers are quoted
in comments as [Eq x.y].
"""
from __future__ import annotations

import copy
import math
import time as _time
from typing import Callable, Optional

import numpy as np
from scipy.integrate import solve_ivp

from ..core.units import (P_STD_ATM, R_GAS, nl_min_to_mol_s, nm3h_to_mol_s, mol_s_to_nm3h)
from . import thermodynamics as td
from .alloying import dissolution_tau
from .balances import ClosureTracker, element_inventory, stored_energy
from .circulation import circulation_rate, gas_holdup_upleg, injection_pressure
from .cleanliness import N_BINS, O_FRAC_AL2O3, inclusion_rates
from .decarburization import apparent_rate_constant, bubble_site, inner_site, surface_site
from .degassing_hn import hydrogen_surface_rate, nitrogen_bubble_peq_effective, nitrogen_kr, nitrogen_surface_rate
from .geometry import derive, vessel_holdup_equilibrium
from .mixing import mixing_time_95
from .oxygen_blow import absorption_efficiency, feo_dissolution_rate, jet_partition, post_combustion
from .properties import (ADDITION_MATERIALS, CP_GAS_MEAN, CP_SLAG, GAS_INDEX, GAS_SPECIES, H_SOLUTION, K_SLAG, MW,
                         SLAG_OXIDES, SPECIES, SPECIES_INDEX, steel_cp_liquid, steel_density, steel_h,
                         steel_T_from_h)
from .state_vector import DC_SITES, ENERGY_TERMS, Layout
from .thermal import (build_wall, initial_profile, radiative_heat_flow, shell_loss, wall_derivatives,
                      wetted_heat_flow)
from .vacuum_gas import (PumpCurve, initial_moles, leak_mol_s, mean_molar_mass, molar_capacity, pressure,
                         throttle)

SI = SPECIES_INDEX
iC, iO, iH, iN, iAl, iSi, iMn, iTi, iS = (SI[k] for k in ["C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "S"])
EIDX = {k: i for i, k in enumerate(ENERGY_TERMS)}
GI = GAS_INDEX
T0_REF = 298.15
O2_PURITY = 0.995  # balance Ar


def _smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class SolverFailure(RuntimeError):
    pass


class RHOBModel:
    """One heat of the RH-OB twin."""

    def __init__(self, plant, heat, schedule, solver_cfg, grade=None, kin_overrides: Optional[dict] = None,
                 guard: Optional[Callable] = None, label: str = "model"):
        self.plant = plant
        self.heat = heat
        self.schedule = copy.deepcopy(schedule)
        self.scfg = solver_cfg
        self.grade = grade
        self.label = label
        self.kin = plant.kinetics.model_copy(update=kin_overrides or {})
        self.th = plant.thermal
        self.vac = plant.vacuum
        self.lim = plant.limits
        self.geom = plant.geometry
        self.guard = guard
        self.P_atm = plant.atmospheric_pressure_Pa
        self.M0 = heat.steel_mass_t * 1000.0
        g = self.geom.model_dump()
        self.dg = derive(g, self.M0)
        self.pump = PumpCurve(self.vac.pump_curve)
        self.zones = ["l", "d", "v"] if (self.kin.three_zone and self.kin.dead_zone_fraction > 0) else ["l", "v"]
        mats = sorted({a.material for a in self.schedule.additions})
        for mname in mats:
            if mname not in ADDITION_MATERIALS:
                raise ValueError(f"unknown addition material '{mname}'")
        self.materials = mats
        nW = self.th.wall_nodes_working_lining
        self.wall_l = build_wall("ladle", g["ladle_wall_layers"], self.dg.r_ladle, self.dg.bath_depth_ladle,
                                 self.dg.A_ladle_wall, nW)
        lower_h = g["vessel_lower_height_m"]
        self.wall_vl = build_wall("vessel_lower", g["vessel_wall_layers"], self.dg.r_vessel, lower_h,
                                  self.dg.A_vessel_lower_wall, nW)
        self.wall_vu = build_wall("vessel_upper", g["upper_vessel_wall_layers"], self.dg.r_vessel,
                                  max(g["vessel_height_m"] - lower_h, 1.0), self.dg.A_vessel_upper_wall, nW)
        self.L = Layout(self.zones, mats, (self.wall_l.n, self.wall_vl.n, self.wall_vu.n))
        # phase table
        self._build_phase_table()
        self.events: list[dict] = []
        self.warnings: list[str] = []
        self.loss_reservoir: dict = {}
        self.charged: dict = {}
        self.lab_samples: list[dict] = []
        self.records: list[dict] = []
        self.t = 0.0
        self.status = "initialized"
        self.vessel_present = False
        self.o2_total_mol = 0.0
        self._ph = None
        self._wall_t0 = None
        self.y = self._initial_state()
        self.closure = ClosureTracker(self)
        self.n_rhs = 0
        self.solver_stats = {"segments": 0, "nfev": 0, "njev": 0, "nlu": 0, "failed_segments": 0}
        self._applied_additions = set()
        self.applied_additions: list[dict] = []
        self._applied_samples = set()
        self._abort_applied = False
        self.paused = False
        self._record(self.t, self.y)

    # ------------------------------------------------------------------ setup
    def _build_phase_table(self):
        self.phase_table = []
        t = 0.0
        prev_o2 = 0.0
        for i, ph in enumerate(self.schedule.phases):
            d = ph.model_dump()
            d.update({"index": i, "t_start": t, "t_end": t + ph.duration_s, "prev_o2": prev_o2,
                      "blocked": False, "block_reason": None})
            if d["pressure_setpoint_end_Pa"] is None:
                d["pressure_setpoint_end_Pa"] = d["pressure_setpoint_Pa"]
            self.phase_table.append(d)
            prev_o2 = ph.oxygen_Nm3_h
            t += ph.duration_s
        self.t_end_schedule = t

    def phase_at(self, t: float) -> dict:
        for ph in self.phase_table:
            if ph["t_start"] <= t < ph["t_end"]:
                return ph
        return self.phase_table[-1]

    def _initial_state(self) -> np.ndarray:
        L, h = self.L, self.heat
        y = np.zeros(L.size)
        w0 = np.zeros(len(SPECIES))
        for k, v in h.composition_ppm.items():
            if k in SI:
                w0[SI[k]] = v * 1e-6
        cp = steel_cp_liquid(w0)
        h0 = steel_h(h.T_arrival_K, cp)
        frac = {"l": 1.0, "d": 0.0, "v": 0.0}
        if "d" in self.zones:
            frac["d"] = self.kin.dead_zone_fraction
            frac["l"] = 1.0 - frac["d"]
        for z in self.zones:
            Mz = self.M0 * frac[z]
            y[L[f"M_{z}"]] = Mz
            y[L[f"H_{z}"]] = Mz * h0
            y[L[f"m_{z}"]] = Mz * w0
        # slag
        ms = h.slag_mass_t * 1000.0
        tot = sum(h.slag_composition_wtpct.values()) or 1.0
        for j, ox in enumerate(SLAG_OXIDES):
            y[L["slag"].start + j] = ms * h.slag_composition_wtpct.get(ox, 0.0) / tot
        T_slag0 = h.T_arrival_K - 60.0
        y[L["H_slag"]] = ms * CP_SLAG * (T_slag0 - T0_REF)
        # walls
        y[L["Tw_ladle"]] = initial_profile(self.wall_l, self.th.ladle_hot_face_initial_K, self.th.ladle_shell_initial_K)
        y[L["Tw_vlow"]] = initial_profile(self.wall_vl, self.th.vessel_preheat_K, self.th.vessel_shell_initial_K)
        y[L["Tw_vup"]] = initial_profile(self.wall_vu, self.th.vessel_preheat_K - 50.0, self.th.vessel_shell_initial_K)
        # gas: air at atmospheric pressure in vessel + duct
        Tg = float(y[L["Tw_vup"]][0])
        n0 = initial_moles(self.P_atm, self.dg.V_vessel_internal, Tg, self.geom.duct_and_cooler_volume_m3,
                           self.vac.duct_gas_temperature_K)
        y[L["gas"].start + GI["N2"]] = 0.79 * n0
        y[L["gas"].start + GI["O2"]] = 0.21 * n0
        return y

    # ------------------------------------------------------------------ inputs
    def _inputs(self, t: float, ph: dict) -> dict:
        tau = t - ph["t_start"]
        dur = max(ph["t_end"] - ph["t_start"], 1e-9)
        frac = min(max(tau / dur, 0.0), 1.0)
        p0, p1 = ph["pressure_setpoint_Pa"], ph["pressure_setpoint_end_Pa"]
        # log-linear pressure ramp (pump-down is approximately exponential)
        p_sp = math.exp(math.log(p0) + (math.log(p1) - math.log(p0)) * frac)
        o2_t = ph["oxygen_Nm3_h"] if not ph["blocked"] else 0.0
        ramp = ph["oxygen_ramp_s"]
        if ramp > 0 and o2_t > 0:  # ramp only when opening; oxygen STOP is immediate (valve closes)
            a = min(tau / ramp, 1.0)
            o2 = ph["prev_o2"] + (o2_t - ph["prev_o2"]) * a if ph["prev_o2"] != o2_t else o2_t
        else:
            o2 = o2_t
        if ph["blocked"]:
            o2 = 0.0
        return {"p_sp": p_sp, "argon": ph["argon_NL_min"], "o2": max(o2, 0.0), "pump_on": ph["vacuum_pump_on"],
                "immersed": ph["snorkels_immersed"], "vent": ph["vent"], "stage": ph["stage"],
                "dispatch": ph["stage"].upper().startswith("DISPATCH")}

    # ------------------------------------------------------------------ RHS
    def rhs(self, t, y):
        return self._f(t, y, False)

    def _f(self, t, y, diag: bool):
        self.n_rhs += 1
        L, kin, th, dg = self.L, self.kin, self.th, self.dg
        inp = self._inputs(t, self._ph)
        dy = np.zeros_like(y)
        E = np.zeros(len(ENERGY_TERMS))
        slag_gain = np.zeros(len(SLAG_OXIDES))
        zones = self.zones
        M, H, m, w, wt, T, hz, f = {}, {}, {}, {}, {}, {}, {}, {}
        for z in zones:
            Mz = y[L[f"M_{z}"]]
            M[z] = Mz
            H[z] = y[L[f"H_{z}"]]
            m[z] = y[L[f"m_{z}"]]
        for z in zones:
            if z == "v" and M["v"] <= 1.0:
                w[z] = w["l"]
                T[z] = T["l"]
                hz[z] = hz["l"]
            else:
                w[z] = m[z] / M[z]
                cpz = steel_cp_liquid(w[z])
                hz[z] = H[z] / M[z]
                T[z] = steel_T_from_h(hz[z], cpz)
            wt[z] = 100.0 * w[z]
            f[z] = td.activity_coefficients(wt[z])
        vessel_on = self.vessel_present and inp["immersed"] and M["v"] > 1.0
        Tl = T["l"]
        rho = steel_density(Tl)
        Tw_l = y[L["Tw_ladle"]]
        Tw_vl = y[L["Tw_vlow"]]
        Tw_vu = y[L["Tw_vup"]]
        # ---------------- vessel geometry & gas pressure [Eq 6.7]
        imm = self.geom.immersion_depth_m
        M_sn_full = rho * 2.0 * dg.A_snorkel * (imm + dg.h_vb0)
        M_v = M["v"]
        steel_in_vessel = max(M_v - M_sn_full, 0.0) if vessel_on else 0.0
        depth_v = steel_in_vessel / (rho * dg.A_vessel)
        pool = _smoothstep(depth_v / 0.10)
        V_free = dg.V_vessel_internal - steel_in_vessel / rho
        Tv = T["v"]
        T_g = 0.5 * (Tv + Tw_vu[0]) if vessel_on else Tw_vu[0]
        n_gas = y[L["gas"]]
        n_tot = float(np.sum(np.maximum(n_gas, 0.0)))
        P = pressure(max(n_tot, 1e-9), V_free, T_g, self.geom.duct_and_cooler_volume_m3, self.vac.duct_gas_temperature_K)
        x = np.maximum(n_gas, 0.0) / max(n_tot, 1e-12)
        # ---------------- hold-up [Eq 6.1b]
        if self.vessel_present and inp["immersed"]:
            M_v_eq, depth_eq, drop = vessel_holdup_equilibrium(dg, self.P_atm, P, rho, imm, True)
            q_h = (M_v_eq - M_v) / kin.holdup_time_constant_s
        else:
            M_v_eq, depth_eq, drop, q_h = 0.0, 0.0, 0.0, 0.0
        # ---------------- argon & circulation [Eq 6.2]
        G = inp["argon"]
        n_ar_tot = nl_min_to_mol_s(G)
        theta = kin.lift_nozzle_fouling
        if inp["immersed"] and self.vessel_present:
            n_ar_v = theta * n_ar_tot
            n_ar_bypass = (1 - theta) * n_ar_tot
        else:
            n_ar_v, n_ar_bypass = 0.0, n_ar_tot
        P1 = injection_pressure(self.P_atm, rho, dg.nozzle_depth_below_level)
        if vessel_on:
            circ = circulation_rate(kin, G, self.geom.snorkel_inner_diameter_m, P1, P, rho, Tl, depth_v)
        else:
            circ = {"q_kg_s": 0.0, "q_raw_kg_s": 0.0, "q_max_kg_s": 0.0, "pool_factor": 0.0, "G_eff_NL_min": 0.0,
                    "u_downleg_m_s": 0.0, "saturation_ratio": 1.0}
        q_c = circ["q_kg_s"]
        has_d = "d" in zones
        q_ex = (kin.dead_zone_exchange_ratio * q_c + kin.dead_zone_natural_exchange_kg_s) if has_d else 0.0
        P_b = (P1 - P) / math.log(P1 / P) if P1 > 1.001 * P else P
        # ---------------- transport between zones [Eq 6.1]
        dM = {z: 0.0 for z in zones}
        dH = {z: 0.0 for z in zones}
        dm = {z: np.zeros(len(SPECIES)) for z in zones}
        inc = {z: y[L[f"inc_{z}"]] for z in zones}
        dinc = {z: np.zeros(N_BINS) for z in zones}
        cinc = {z: (inc[z] / M[z] if M[z] > 1.0 else (inc["l"] / M["l"])) for z in zones}
        if self.vessel_present:
            # circulation loop l -> v (up-leg) -> l (down-leg)
            dm["l"] += q_c * (w["v"] - w["l"])
            dm["v"] += q_c * (w["l"] - w["v"])
            dH["l"] += q_c * (hz["v"] - hz["l"])
            dH["v"] += q_c * (hz["l"] - hz["v"])
            dinc["l"] += q_c * (cinc["v"] - cinc["l"])
            dinc["v"] += q_c * (cinc["l"] - cinc["v"])
            # hold-up change (donor composition)
            donor = "l" if q_h >= 0 else "v"
            dM["l"] -= q_h
            dM["v"] += q_h
            dm["l"] -= q_h * w[donor]
            dm["v"] += q_h * w[donor]
            dH["l"] -= q_h * hz[donor]
            dH["v"] += q_h * hz[donor]
            dinc["l"] -= q_h * cinc[donor]
            dinc["v"] += q_h * cinc[donor]
        if has_d:
            dm["l"] += q_ex * (w["d"] - w["l"])
            dm["d"] += q_ex * (w["l"] - w["d"])
            dH["l"] += q_ex * (hz["d"] - hz["l"])
            dH["d"] += q_ex * (hz["l"] - hz["d"])
            dinc["l"] += q_ex * (cinc["d"] - cinc["l"])
            dinc["d"] += q_ex * (cinc["l"] - cinc["d"])
        # gas source terms (mol/s) into vessel gas phase
        gsrc = np.zeros(len(GAS_SPECIES))
        gas_sens = 0.0  # W, sensible heat of gases leaving / heated by the bath
        D = {}  # diagnostics
        # ---------------- vessel reactions
        r_surf = r_in = z_star = 0.0
        bub = {"CO": 0.0, "H2": 0.0, "N2": 0.0, "capped": False}
        jet = {"Al": 0.0, "Ti": 0.0, "Si": 0.0, "C": 0.0, "Mn": 0.0, "FeO": 0.0}
        n_o2_inj = nm3h_to_mol_s(inp["o2"]) * O2_PURITY if inp["o2"] > 0 else 0.0
        n_ar_o2imp = nm3h_to_mol_s(inp["o2"]) * (1 - O2_PURITY) if inp["o2"] > 0 else 0.0
        eta_abs = 0.0
        n_slip = 0.0
        r_H = r_N = 0.0
        A_surf = 0.0
        surf_factor = 0.0
        r_feo_diss = r_feo_skull = 0.0
        n_pc_co = n_pc_o2 = 0.0
        kr_v = 0.0
        pool_feo = y[L["feo_pool"]]
        leak_frac = min(max((self.P_atm - P) / (0.5 * self.P_atm), 0.0), 1.0)
        n_leak_N2, n_leak_O2 = leak_mol_s(self.vac.air_leak_kg_h * leak_frac)
        n_leak_O_abs = 0.0
        if vessel_on:
            wv, ftv = wt["v"], f["v"]
            Cv, Ov = wv[iC], wv[iO]
            U_g = n_ar_v * R_GAS * Tv / P / dg.A_vessel
            surf_factor = min(1.0 + kin.splash_enhancement * math.sqrt(U_g), kin.splash_enhancement_max)
            A_surf = dg.A_vessel * surf_factor * pool + 2.0 * dg.A_snorkel * (1.0 - pool)
            r_surf = surface_site(Cv, Ov, Tv, P, x[GI["CO"]], ftv[iC], ftv[iO], rho, A_surf, kin)
            r_in, z_star = inner_site(Cv, Ov, Tv, P, ftv[iC], ftv[iO], rho, dg.A_vessel, depth_v, kin)
            # bubble site with up-leg (ladle active zone) melt
            wl, fl = wt["l"], f["l"]
            kr_l = nitrogen_kr(kin, wl[iO], wl[iS], fl[iO], fl[SI["S"]])
            p_eq_b = {"CO": td.p_co_equilibrium_pa(Tl, wl[iC], wl[iO], fl[iC], fl[iO]),
                      "H2": td.p_h2_eq_pa(Tl, wl[iH], fl[iH]),
                      "N2": nitrogen_bubble_peq_effective(wl[iN], Tl, fl[iN], kr_l, kin.k_r0_N_mol_m2_s_atm)}
            bub = bubble_site(n_ar_v, P_b, p_eq_b, kin.bubble_equilibrium_approach, q_c, w["l"][iC])
            # oxygen blowing [Eq 6.5]
            if n_o2_inj > 0:
                h_sub = depth_v - self.geom.oxygen_tuyere_height_above_bottom_m
                eta_abs = absorption_efficiency(kin.o2_absorption_lambda, h_sub) if self.geom.oxygen_tuyere_count > 0 else 0.0
                n_O_abs = 2.0 * eta_abs * n_o2_inj
                jet = jet_partition(n_O_abs, {k: wv[SI[k]] for k in ["Al", "Ti", "Si", "C", "Mn"]}, rho,
                                    kin.jet_mass_transfer_capacity_m3_s)
                n_slip = (1.0 - eta_abs) * n_o2_inj
            O_sat = td.o_saturation_feo(Tv, ftv[iO])
            r_feo_diss = feo_dissolution_rate(pool_feo, kin.feo_dissolution_1_s, Ov, O_sat)
            r_feo_skull = kin.feo_to_skull_1_s * max(pool_feo, 0.0)
            # H and N at the free surface [Eq 6.6]
            r_H = hydrogen_surface_rate(wv[iH], Tv, x[GI["H2"]] * P, ftv[iH], rho, kin.k_H_m_s, A_surf)
            kr_v = nitrogen_kr(kin, Ov, wv[iS], ftv[iO], ftv[SI["S"]])
            r_N, N_i = nitrogen_surface_rate(wv[iN], Tv, x[GI["N2"]] * P, ftv[iN], rho, kin.k_N_m_s, A_surf, kr_v)
            n_leak_O_abs = 2.0 * kin.leak_o2_absorption * n_leak_O2 * pool
        else:
            r_feo_skull = kin.feo_to_skull_1_s * max(pool_feo, 0.0) if pool_feo > 0 else 0.0
        # ---- apply vessel reaction terms
        if vessel_on:
            n_CO_dc = r_surf + r_in + bub["CO"]
            dm["v"][iC] -= (n_CO_dc + jet["C"]) * MW["C"]
            dm["v"][iO] -= n_CO_dc * MW["O"]
            dM["v"] -= n_CO_dc * MW["CO"] + jet["C"] * MW["C"]
            E[EIDX["rxn_C_O_CO"]] += -td.DH["C_O_CO"] * (n_CO_dc + jet["C"])
            # jet: O2 -> 2[O] (Hess path) then oxide formation from [O]
            n_O_abs = 2.0 * eta_abs * n_o2_inj
            E[EIDX["rxn_O2_to_O"]] += -td.DH["O2_O"] * n_O_abs
            for el, ox, n_o, key in [("Al", "Al2O3", 1.5, "Al_deox"), ("Si", "SiO2", 2.0, "Si_deox"),
                                     ("Ti", "TiO2", 2.0, "Ti_deox"), ("Mn", "MnO", 1.0, "Mn_deox")]:
                n_el = jet[el]
                if n_el > 0:
                    dm["v"][SI[el]] -= n_el * MW[el]
                    dM["v"] -= n_el * MW[el]
                    n_ox = n_el / (2.0 if el == "Al" else 1.0)
                    E[EIDX[f"rxn_{ox}"]] += -td.DH[key] * n_ox
                    slag_gain[SLAG_OXIDES.index(ox)] += n_ox * MW[ox]
            n_feo = jet["FeO"]
            dM["v"] -= n_feo * MW["Fe"]
            E[EIDX["rxn_FeO_form"]] += -td.DH["FeO_O"] * n_feo
            dy[L["feo_pool"]] += n_feo * MW["FeO"]
            # FeO dissolution FeO -> Fe + [O]
            n_diss = r_feo_diss / MW["FeO"]
            dy[L["feo_pool"]] -= r_feo_diss + r_feo_skull
            dM["v"] += r_feo_diss
            dm["v"][iO] += n_diss * MW["O"]
            E[EIDX["rxn_FeO_diss"]] += td.DH["FeO_O"] * n_diss
            # leak O2 absorbed
            dm["v"][iO] += n_leak_O_abs * MW["O"]
            dM["v"] += n_leak_O_abs * MW["O"]
            E[EIDX["rxn_O2_to_O"]] += -td.DH["O2_O"] * n_leak_O_abs
            # H, N removal (surface + bubbles)
            rH_tot = r_H + bub["H2"] * MW["H2"]
            rN_tot = r_N + bub["N2"] * MW["N2"]
            dm["v"][iH] -= rH_tot
            dm["v"][iN] -= rN_tot
            dM["v"] -= rH_tot + rN_tot
            E[EIDX["rxn_degas_HN"]] += td.DH["H2_H"] * rH_tot / MW["H"] + td.DH["N2_N"] * rN_tot / MW["N"]
            # gas sources
            gsrc[GI["CO"]] += n_CO_dc + jet["C"]
            gsrc[GI["H2"]] += rH_tot / MW["H2"]
            gsrc[GI["N2"]] += rN_tot / MW["N2"]
            gsrc[GI["Ar"]] += n_ar_v + n_ar_o2imp
            gsrc[GI["O2"]] += n_slip
            # post-combustion in freeboard [Eq 6.5d]
            n_pc_co, n_pc_o2 = post_combustion(n_slip, n_CO_dc + jet["C"], kin.post_combustion_fraction)
            gsrc[GI["CO"]] -= n_pc_co
            gsrc[GI["CO2"]] += n_pc_co
            gsrc[GI["O2"]] -= n_pc_o2
            q_pc = -td.DH_CO_POSTCOMB * n_pc_co
            E[EIDX["pc_to_bath"]] += kin.post_combustion_heat_to_bath * q_pc
            E[EIDX["int_pc_to_offgas"]] += (1 - kin.post_combustion_heat_to_bath) * q_pc
            # sensible heat of gases leaving the bath / heating of injected O2
            gas_sens += ((n_ar_v + n_ar_o2imp) * CP_GAS_MEAN["Ar"] + (n_CO_dc + jet["C"]) * CP_GAS_MEAN["CO"]
                         + (rH_tot / MW["H2"]) * CP_GAS_MEAN["H2"] + (rN_tot / MW["N2"]) * CP_GAS_MEAN["N2"]
                         + n_o2_inj * CP_GAS_MEAN["O2"] + 0.5 * n_leak_O_abs * CP_GAS_MEAN["O2"]) * (Tv - T0_REF)
            dH["v"] += E[EIDX["rxn_C_O_CO"]] + E[EIDX["rxn_O2_to_O"]] + E[EIDX["rxn_Al2O3"]] + E[EIDX["rxn_SiO2"]] \
                + E[EIDX["rxn_TiO2"]] + E[EIDX["rxn_MnO"]] + E[EIDX["rxn_FeO_form"]] + E[EIDX["rxn_FeO_diss"]] \
                + E[EIDX["rxn_degas_HN"]] + E[EIDX["pc_to_bath"]] - gas_sens
        else:
            dy[L["feo_pool"]] -= r_feo_skull
            gsrc[GI["O2"]] += n_o2_inj  # oxygen with no bath: straight to off-gas (guard should prevent)
            gsrc[GI["Ar"]] += n_ar_o2imp
        # bypassing argon heated by ladle steel
        q_bypass = n_ar_bypass * CP_GAS_MEAN["Ar"] * (Tl - T0_REF)
        dH["l"] -= q_bypass
        gas_sens_total = gas_sens + q_bypass
        # ---------------- deoxidation in every zone [Eq 6.9]
        rdeox = {}
        for z in zones:
            if z == "v" and not vessel_on:
                continue
            Mz = M[z]
            wz, fz = wt[z], f[z]
            Tz = T[z]
            O = wz[iO]
            out = {}
            for el, key, eqf, ox, o_per_ox, el_per_ox in [
                    ("Al", "Al_deox", td.o_eq_al, "Al2O3", 3, 2), ("Ti", "Ti_deox", td.o_eq_ti, "TiO2", 2, 1),
                    ("Si", "Si_deox", td.o_eq_si, "SiO2", 2, 1), ("Mn", "Mn_deox", td.o_eq_mn, "MnO", 1, 1)]:
                if wz[SI[el]] <= 1e-7:
                    continue
                O_eq = eqf(Tz, wz[SI[el]], fz[SI[el]], fz[iO])
                if O <= O_eq:
                    continue
                rO = kin.deox_rate_1_s * Mz * (O - O_eq) / 100.0  # kg O/s
                n_ox = rO / (o_per_ox * MW["O"])
                r_el = n_ox * el_per_ox * MW[el]
                dm[z][iO] -= rO
                dm[z][SI[el]] -= r_el
                dM[z] -= rO + r_el
                q = -td.DH[key] * n_ox
                dH[z] += q
                E[EIDX[f"rxn_{ox}"]] += q
                if ox == "Al2O3":
                    dinc[z][0] += n_ox * MW[ox]
                else:
                    slag_gain[SLAG_OXIDES.index(ox)] += n_ox * MW[ox]
                out[el] = rO
            rdeox[z] = out
        # ---------------- slag-metal reoxidation, ladle active zone [Eq 6.9c]
        slag = y[L["slag"]]
        m_slag = float(np.sum(np.maximum(slag, 0.0)))
        H_slag = y[L["H_slag"]]
        T_slag = T0_REF + H_slag / (m_slag * CP_SLAG) if m_slag > 10.0 else Tl
        J_O = 0.0
        q_sm = q_top = 0.0
        A_top = dg.A_ladle_top_open
        if m_slag > 10.0:
            mol = np.maximum(slag, 0.0) / np.array([MW[o] for o in SLAG_OXIDES])
            X_feo = mol[0] / max(np.sum(mol), 1e-12)
            a_feo = kin.gamma_FeO_slag * X_feo
            O_eq_s = td.o_saturation_feo(Tl, f["l"][iO], a_feo)
            J_O = kin.k_slag_metal_m_s * A_top * rho * (O_eq_s - wt["l"][iO]) / 100.0  # kg O/s into steel
            n_o = J_O / MW["O"]
            if J_O < 0 and wt["l"][iO] <= 0:
                J_O, n_o = 0.0, 0.0
            dm["l"][iO] += J_O
            dM["l"] += n_o * MW["FeO"]
            dy[L["slag"].start + 0] -= n_o * MW["FeO"]
            h_slag = H_slag / m_slag
            if n_o >= 0:
                dH["l"] += n_o * MW["FeO"] * h_slag
                dy[L["H_slag"]] -= n_o * MW["FeO"] * h_slag
            else:
                dH["l"] += n_o * MW["FeO"] * hz["l"]
                dy[L["H_slag"]] -= n_o * MW["FeO"] * hz["l"]
            q_rx = td.DH["FeO_O"] * n_o
            dH["l"] += q_rx
            E[EIDX["rxn_slag_reox"]] += q_rx
            # slag thermal: conduction through half slag layer + film; top radiation
            delta = max(th.slag_thickness_m, 0.005)
            G_sm = A_top / (1.0 / 1000.0 + 0.5 * delta / K_SLAG)
            q_sm = G_sm * (Tl - T_slag)
            G_half = K_SLAG * A_top / (0.5 * delta)
            F = th.view_factor_ladle_top * (0.25 if inp["dispatch"] else 1.0)
            Ts = T_slag
            for _ in range(5):
                fr = G_half * (T_slag - Ts) - 5.670374419e-8 * th.emissivity_slag * F * A_top * (Ts ** 4 - th.surroundings_temperature_K ** 4)
                dfr = -G_half - 4 * 5.670374419e-8 * th.emissivity_slag * F * A_top * Ts ** 3
                Ts -= fr / dfr
            q_top = G_half * (T_slag - Ts)
            dH["l"] -= q_sm
            dy[L["H_slag"]] += q_sm - q_top
            E[EIDX["int_steel_to_slag"]] += q_sm
            E[EIDX["loss_slag_top"]] += q_top
        # ---------------- additions dissolution [Eq 6.9a]
        add_diag = {}
        if self.materials:
            ia = L["add"].start
            tgt = "v" if vessel_on else "l"
            Ttgt = T[tgt]
            for j, mat in enumerate(self.materials):
                ma = y[ia + j]
                if ma <= 0:
                    continue
                tau = dissolution_tau(mat, Ttgt)
                r = ma / tau
                dy[ia + j] -= r
                comp = ADDITION_MATERIALS[mat]["comp"]
                q_sol = 0.0
                for el, fr_ in comp.items():
                    if el in SI:
                        dm[tgt][SI[el]] += r * fr_
                    q_sol += -H_SOLUTION.get(el, 0.0) * r * fr_ / MW[el]
                dM[tgt] += r
                dH[tgt] += q_sol
                E[EIDX["rxn_solution"]] += q_sol
                add_diag[mat] = {"rate_kg_s": r, "tau_s": tau}
        # ---------------- inclusions [Eq 6.9b]
        Mlad = M["l"] + (M["d"] if has_d else 0.0)
        u_dn = circ["u_downleg_m_s"]
        eps_l = (0.5 * q_c * u_dn ** 2 + n_ar_bypass * R_GAS * Tl * math.log(P1 / self.P_atm)) / max(Mlad, 1.0)
        eps_v = (n_ar_v * R_GAS * Tl * math.log(max(P1 / P, 1.0))) / max(M_v, 1.0) if vessel_on else 0.0
        q_ar_nm3_s = n_ar_v * 0.022414
        inc_removed_slag = inc_removed_vessel = 0.0
        for z in zones:
            if z == "v" and not vessel_on:
                continue
            Hz = self.dg.bath_depth_ladle if z in ("l", "d") else max(depth_v, 0.1)
            epsz = eps_v if z == "v" else (eps_l if z == "l" else 0.2 * eps_l)
            d_inc, rem_surf, rem_bub = inclusion_rates(inc[z], M[z], rho, epsz, Hz, q_ar_nm3_s,
                                                       kin.inclusion_bubble_capture,
                                                       kin.inclusion_aggregation_multiplier, z == "v")
            dinc[z] += d_inc
            if z == "v":
                inc_removed_vessel += rem_surf + rem_bub
            else:
                inc_removed_slag += rem_surf
        slag_gain[SLAG_OXIDES.index("Al2O3")] += inc_removed_slag
        # ---------------- walls [Eq 6.8]
        phi_d = min(2.0 * kin.dead_zone_fraction, 0.6) if has_d else 0.0
        q_lw = wetted_heat_flow(self.wall_l, Tl, Tw_l[0], th.h_steel_ladle_wall_W_m2K) * (1 - phi_d)
        q_dw = wetted_heat_flow(self.wall_l, T["d"], Tw_l[0], th.h_steel_ladle_wall_W_m2K) * phi_d if has_d else 0.0
        q_lout, Ts_l = shell_loss(self.wall_l, Tw_l[-1], th.h_shell_convection_W_m2K, th.emissivity_shell, th.ambient_temperature_K)
        dy[L["Tw_ladle"]] = wall_derivatives(self.wall_l, Tw_l, q_lw + q_dw, q_lout)
        dH["l"] -= q_lw
        if has_d:
            dH["d"] -= q_dw
        if vessel_on:
            wet_frac = min((2 * math.pi * self.geom.snorkel_inner_diameter_m * self.geom.snorkel_length_m
                            + dg.A_vessel * pool + math.pi * 2 * dg.r_vessel * depth_v) / self.wall_vl.A_in, 1.0)
            q_vlw = wetted_heat_flow(self.wall_vl, Tv, Tw_vl[0], th.h_steel_vessel_wall_W_m2K) * wet_frac
            q_vuw, Ts_up = radiative_heat_flow(self.wall_vu, Tv, dg.A_vessel * pool + 1e-6, th.emissivity_steel, Tw_vu[0])
        else:
            q_vlw = q_vuw = 0.0
        q_vlout, Ts_vl = shell_loss(self.wall_vl, Tw_vl[-1], th.h_shell_convection_W_m2K, th.emissivity_shell, th.ambient_temperature_K)
        q_vuout, Ts_vu = shell_loss(self.wall_vu, Tw_vu[-1], th.h_shell_convection_W_m2K, th.emissivity_shell, th.ambient_temperature_K)
        dy[L["Tw_vlow"]] = wall_derivatives(self.wall_vl, Tw_vl, q_vlw, q_vlout)
        dy[L["Tw_vup"]] = wall_derivatives(self.wall_vu, Tw_vu, q_vuw, q_vuout)
        if vessel_on:
            dH["v"] -= q_vlw + q_vuw
        E[EIDX["int_to_ladle_wall"]] += q_lw + q_dw
        E[EIDX["int_to_vlow_wall"]] += q_vlw
        E[EIDX["int_to_vup_wall"]] += q_vuw
        E[EIDX["loss_ladle_shell"]] += q_lout
        E[EIDX["loss_vlow_shell"]] += q_vlout
        E[EIDX["loss_vup_shell"]] += q_vuout
        E[EIDX["gas_sensible_out"]] += gas_sens_total
        # ---------------- vacuum pump, leak, vent, relief [Eq 6.7]
        Mg = mean_molar_mass(n_gas)
        n_cap = molar_capacity(self.pump, P, Mg, self.vac.pump_health) if inp["pump_on"] else 0.0
        u = throttle(P, inp["p_sp"], self.vac.pressure_controller_band_frac)
        n_exh = n_cap * u
        n_relief = 0.02 * max(P - self.P_atm, 0.0)  # relief flap at > atmospheric
        n_open = 0.02 * max(self.P_atm - P, 0.0) if not inp["immersed"] else 0.0  # vessel open to air after withdrawal
        n_vent = 0.0
        if inp["vent"]:
            n_vent = self.vac.vent_rate_mol_s * 0.5 * (1.0 - math.tanh((P - 0.985 * self.P_atm) / 800.0))
        vent_vec = np.zeros(len(GAS_SPECIES))
        if n_vent > 0:
            if self.vac.vent_gas == "N2":
                vent_vec[GI["N2"]] = n_vent
            elif self.vac.vent_gas == "Ar":
                vent_vec[GI["Ar"]] = n_vent
            else:
                vent_vec[GI["N2"]] = 0.79 * n_vent
                vent_vec[GI["O2"]] = 0.21 * n_vent
        leak_vec = np.zeros(len(GAS_SPECIES))
        leak_vec[GI["N2"]] = n_leak_N2
        leak_vec[GI["O2"]] = n_leak_O2 - 0.5 * n_leak_O_abs
        leak_vec[GI["N2"]] += 0.79 * n_open
        leak_vec[GI["O2"]] += 0.21 * n_open
        gsrc += leak_vec + vent_vec
        out_flow = n_exh + n_relief
        dy[L["gas"]] = gsrc - x * out_flow
        acc_in = np.zeros(len(GAS_SPECIES))
        acc_in[GI["Ar"]] = n_ar_tot + n_ar_o2imp + vent_vec[GI["Ar"]]
        acc_in[GI["O2"]] = n_o2_inj + n_leak_O2 + vent_vec[GI["O2"]] + 0.21 * n_open
        acc_in[GI["N2"]] = n_leak_N2 + vent_vec[GI["N2"]] + 0.79 * n_open
        dy[L["acc_in"]] = acc_in
        dy[L["acc_exh"]] = x * out_flow
        dy[L["acc_bypass_ar"]] = n_ar_bypass
        dy[L["acc_o2_tuyere"]] = n_o2_inj
        dy[L["acc_skull"].start + 0] = r_feo_skull
        dy[L["acc_skull"].start + 1] = inc_removed_vessel
        dy[L["acc_circ"]] = q_c
        dcs = L["acc_dc"].start
        dy[dcs + 0] = r_surf
        dy[dcs + 1] = r_in
        dy[dcs + 2] = bub["CO"]
        dy[dcs + 3] = jet["C"]
        # slag gains (oxides from deoxidation / jet / flotation)
        dy[L["slag"]] += slag_gain
        # ---------------- assemble zone derivatives
        for z in zones:
            if z == "v" and not self.vessel_present:
                continue
            dy[L[f"M_{z}"]] = dM[z]
            dy[L[f"H_{z}"]] = dH[z]
            dy[L[f"m_{z}"]] = dm[z]
            dy[L[f"inc_{z}"]] = dinc[z]
        dy[L["acc_E"]] = E
        if not diag:
            return dy
        # ---------------- diagnostics
        Mb = sum(M[z] for z in zones)
        wb = sum(m[z] for z in zones) / Mb
        Hb = sum(H[z] for z in zones)
        cpb = steel_cp_liquid(wb)
        Tb = steel_T_from_h(Hb / Mb, cpb)
        Mlad_ = M["l"] + (M["d"] if has_d else 0.0)
        wlad = (m["l"] + (m["d"] if has_d else 0.0)) / Mlad_
        tmix = mixing_time_95(M["l"], M["d"] if has_d else 0.0, max(M_v, 1.0), q_c, q_ex) if q_c > 0 else float("inf")
        K_app = apparent_rate_constant(q_c, Mb, rho, kin.k_C_surface_m_s * A_surf) if vessel_on else 0.0
        S_act = n_exh * R_GAS * self.vac.suction_temperature_K / P if P > 0 else 0.0
        inc_tot = sum(float(np.sum(np.maximum(inc[z], 0.0))) for z in zones)
        D.update({
            "t_s": t, "stage": inp["stage"], "P_Pa": P, "P_sp_Pa": inp["p_sp"], "argon_NL_min": G, "oxygen_Nm3_h": inp["o2"],
            "T_l_K": Tl, "T_d_K": T.get("d", Tl), "T_v_K": Tv if vessel_on else float("nan"), "T_bulk_K": Tb,
            "T_slag_K": T_slag, "T_gas_K": T_g,
            "M_l_kg": M["l"], "M_d_kg": M.get("d", 0.0), "M_v_kg": M_v, "M_v_eq_kg": M_v_eq, "M_total_kg": Mb,
            "vessel_depth_m": depth_v, "ladle_level_drop_m": drop, "q_circ_kg_s": q_c, "q_circ_t_min": q_c * 0.06,
            "q_raw_t_min": circ["q_raw_kg_s"] * 0.06, "q_exchange_kg_s": q_ex, "u_downleg_m_s": u_dn,
            "mixing_time_95_s": tmix if math.isfinite(tmix) else None, "K_app_1_min": K_app * 60.0,
            "gas_holdup_upleg": gas_holdup_upleg(G * theta, self.geom.snorkel_inner_diameter_m, P_b, Tl, u_dn) if vessel_on else 0.0,
            "P_inj_Pa": P1, "P_bubble_Pa": P_b, "surface_area_m2": A_surf, "surface_factor": surf_factor,
            "inner_site_depth_m": z_star,
            "r_C_surface_mol_s": r_surf, "r_C_inner_mol_s": r_in, "r_C_bubble_mol_s": bub["CO"], "r_C_jet_mol_s": jet["C"],
            "bubble_capped": bub["capped"],
            "o2_abs_eff": eta_abs, "o2_slip_mol_s": n_slip, "o2_inj_mol_s": n_o2_inj,
            "jet_O_to_C_mol_s": jet["C"], "jet_O_to_FeO_mol_s": jet["FeO"], "jet_Al_mol_s": jet["Al"], "jet_Si_mol_s": jet["Si"],
            "jet_Mn_mol_s": jet["Mn"], "jet_Ti_mol_s": jet["Ti"], "feo_pool_kg": pool_feo, "feo_diss_kg_s": r_feo_diss,
            "pc_CO_mol_s": n_pc_co, "leak_O_abs_mol_s": n_leak_O_abs,
            "r_H_surface_kg_s": r_H, "r_H_bubble_kg_s": bub["H2"] * MW["H2"], "r_N_surface_kg_s": r_N,
            "r_N_bubble_kg_s": bub["N2"] * MW["N2"], "k_r_N": kr_v,
            "pump_capacity_mol_s": n_cap, "pump_throttle": u, "exhaust_mol_s": n_exh, "pump_S_actual_m3_s": S_act,
            "pump_w_air_kg_h": self.pump.w_air_kg_h(P) * self.vac.pump_health, "vent_mol_s": n_vent,
            "gas_molar_mass": Mg, "slag_metal_O_kg_s": J_O, "q_slag_top_W": q_top, "q_steel_slag_W": q_sm,
            "q_ladle_wall_W": q_lw + q_dw, "q_vlow_wall_W": q_vlw, "q_vup_wall_W": q_vuw, "q_ladle_shell_W": q_lout,
            "q_vlow_shell_W": q_vlout, "q_vup_shell_W": q_vuout, "q_gas_sensible_W": gas_sens_total,
            "T_ladle_hotface_K": Tw_l[0], "T_ladle_shell_K": Ts_l, "T_vlow_hotface_K": Tw_vl[0], "T_vlow_shell_K": Ts_vl,
            "T_vup_hotface_K": Tw_vu[0], "T_vup_shell_K": Ts_vu, "eps_ladle_W_kg": eps_l, "eps_vessel_W_kg": eps_v,
            "inclusions_total_kg": inc_tot, "additions": add_diag,
        })
        for k, i in GI.items():
            D[f"x_{k}"] = x[i]
            D[f"offgas_{k}_Nm3_h"] = mol_s_to_nm3h(x[i] * out_flow)
        for s in SPECIES:
            D[f"{s}_bulk_ppm"] = wb[SI[s]] * 1e6
            D[f"{s}_ladle_ppm"] = wlad[SI[s]] * 1e6
            D[f"{s}_vessel_ppm"] = w["v"][SI[s]] * 1e6 if vessel_on else float("nan")
        for j, ox in enumerate(SLAG_OXIDES):
            D[f"slag_{ox}_kg"] = float(slag[j])
        D["slag_mass_kg"] = m_slag
        for k, v in enumerate(E):
            D[f"Q_{ENERGY_TERMS[k]}_W"] = float(v)
        # equilibrium references
        fv = f["v"] if vessel_on else f["l"]
        Tref = Tv if vessel_on else Tl
        D["C_eq_surface_ppm"] = td.co_equilibrium_product(Tref, max(x[GI["CO"]] * P, 1.0), fv[iC], fv[iO]) / max(wt["v" if vessel_on else "l"][iO], 1e-6) * 1e4
        D["p_CO_eq_bulk_Pa"] = td.p_co_equilibrium_pa(Tref, wb[iC] * 100, wb[iO] * 100, fv[iC], fv[iO])
        D["H_eq_ppm"] = td.h_sieverts_pct(Tref, max(x[GI["H2"]] * P, 1e-6), fv[iH]) * 1e4
        D["N_eq_ppm"] = td.n_sieverts_pct(Tref, max(x[GI["N2"]] * P, 1e-6), fv[iN]) * 1e4
        wl_ = wt["l"]
        D["O_eq_Al_ppm"] = td.o_eq_al(Tl, wl_[iAl], f["l"][iAl], f["l"][iO]) * 1e4 if wl_[iAl] > 1e-5 else None
        incl_O = sum(float(np.sum(np.maximum(inc[z], 0.0))) for z in zones) * O_FRAC_AL2O3
        D["total_O_ppm"] = (wb[iO] * Mb + incl_O) / Mb * 1e6
        D["inclusion_bins_ppm"] = (sum(np.maximum(inc[z], 0.0) for z in zones) / Mb * 1e6).tolist()
        D["liquidus_K"] = liquidus_K(wb)
        D["superheat_K"] = Tb - D["liquidus_K"]
        return dy, D

    # ------------------------------------------------------------------ discrete events
    def _apply_immersion(self):
        """Snorkels enter the steel: fill snorkels to ladle level with ladle-active steel."""
        L = self.L
        y = self.y
        Ml = y[L["M_l"]]
        wl = y[L["m_l"]] / Ml
        hl = y[L["H_l"]] / Ml
        rho = steel_density(steel_T_from_h(hl, steel_cp_liquid(wl)))
        M_eq, _, _ = vessel_holdup_equilibrium(self.dg, self.P_atm, self.P_atm, rho, self.geom.immersion_depth_m, True)
        frac = M_eq / Ml
        for blk in ["M", "H", "m", "inc"]:
            y[L[f"{blk}_v"]] = y[L[f"{blk}_l"]] * frac
            y[L[f"{blk}_l"]] = y[L[f"{blk}_l"]] * (1 - frac)
        self.vessel_present = True
        self._event("IMMERSION", f"snorkels immersed; {M_eq/1000:.2f} t steel in snorkels")

    def _apply_withdrawal(self):
        L = self.L
        y = self.y
        for blk in ["M", "H", "m", "inc"]:
            y[L[f"{blk}_l"]] = y[L[f"{blk}_l"]] + y[L[f"{blk}_v"]]
            y[L[f"{blk}_v"]] = 0.0 * y[L[f"{blk}_v"]]
        pool = y[L["feo_pool"]]
        y[L["acc_skull"].start] += pool
        y[L["feo_pool"]] = 0.0
        self.vessel_present = False
        self._event("WITHDRAWAL", "snorkels withdrawn; vessel steel drained to ladle; residual FeO to skull")

    def _apply_addition(self, a):
        mat = ADDITION_MATERIALS[a.material]
        yld = a.yield_override if a.yield_override is not None else mat["yield_default"]
        if a.auto_target_Al_ppm is not None and a.material == "Al_shot":
            # O-probe based deoxidation calculation (as practised in plants): Al to remove the
            # measured dissolved O plus reach the Al target
            _, D = self._f(self.t, self.y, True)
            Mb = D["M_total_kg"]
            need_ppm = D["O_bulk_ppm"] * (2 * MW["Al"]) / (3 * MW["O"]) + a.auto_target_Al_ppm - max(D["Al_bulk_ppm"], 0.0)
            mass = max(need_ppm, 0.0) * 1e-6 * Mb / (yld * mat["comp"]["Al"])
            a = a.model_copy(update={"mass_kg": round(mass, 1)})
            self._event("DEOX_CALC", f"O-probe deoxidation: O={D['O_bulk_ppm']:.0f} ppm, Al={D['Al_bulk_ppm']:.0f} ppm "
                        f"-> {a.mass_kg:.0f} kg Al for target {a.auto_target_Al_ppm:.0f} ppm")
        self.applied_additions.append(a.model_dump())
        m_in = a.mass_kg * yld
        j = self.materials.index(a.material)
        self.y[self.L["add"].start + j] += m_in
        for el, fr in mat["comp"].items():
            self.charged[el] = self.charged.get(el, 0.0) + a.mass_kg * fr
            self.loss_reservoir[el] = self.loss_reservoir.get(el, 0.0) + a.mass_kg * (1 - yld) * fr
        self._event("ADDITION", f"{a.mass_kg:.0f} kg {a.material} ({a.purpose}), yield {yld:.2f}",
                    {"material": a.material, "mass_kg": a.mass_kg, "yield": yld})

    def _event(self, kind, msg, data=None, severity="info"):
        self.events.append({"t_s": round(self.t, 3), "kind": kind, "message": msg, "severity": severity,
                            "data": data or {}, "source": self.label})

    # ------------------------------------------------------------------ integration
    def breakpoints(self, t0, t1):
        bps = {t1}
        for ph in self.phase_table:
            if t0 < ph["t_start"] < t1:
                bps.add(ph["t_start"])
        for a in self.schedule.additions:
            if t0 < a.t_s < t1:
                bps.add(a.t_s)
        for s in self.schedule.samples:
            if t0 < s.t_s < t1:
                bps.add(s.t_s)
        if self.schedule.abort_at_s and t0 < self.schedule.abort_at_s < t1:
            bps.add(self.schedule.abort_at_s)
        return sorted(bps)

    def _atol(self):
        L = self.L
        a = np.full(self.L.size, 1e-3)
        for z in self.zones:
            a[L[f"M_{z}"]] = 1e-2
            a[L[f"H_{z}"]] = 1e3
            sl = L[f"m_{z}"]
            a[sl] = 1e-6
            a[sl.start + iH] = 1e-8
            a[L[f"inc_{z}"]] = 1e-7
        a[L["Tw_ladle"]] = 1e-4
        a[L["Tw_vlow"]] = 1e-4
        a[L["Tw_vup"]] = 1e-4
        a[L["gas"]] = 1e-6
        a[L["acc_E"]] = 1e2
        a[L["H_slag"]] = 1e2
        a[L["acc_circ"]] = 1.0
        return a

    def _enter_phase(self, t):
        ph = self.phase_at(t)
        if self._ph is not ph:
            prev = self._ph
            self._ph = ph
            # immersion / withdrawal events
            if ph["snorkels_immersed"] and not self.vessel_present:
                self._apply_immersion()
            if (not ph["snorkels_immersed"]) and self.vessel_present:
                self._apply_withdrawal()
            # guards (state machine)
            if self.guard is not None:
                ok, reason = self.guard(self, ph, prev)
                if not ok:
                    ph["blocked"] = True
                    ph["block_reason"] = reason
                    self._event("TRANSITION_BLOCKED", f"{ph['stage']}: {reason}", {"reason_code": reason}, "warning")
            self._event("STAGE", f"enter {ph['stage']}", {"index": ph["index"], "blocked": ph["blocked"]})

    def _discrete_at(self, t):
        for k, a in enumerate(self.schedule.additions):
            if k not in self._applied_additions and a.t_s <= t + 1e-6:
                self._apply_addition(a)
                self._applied_additions.add(k)
        for k, s in enumerate(self.schedule.samples):
            if k not in self._applied_samples and s.t_s <= t + 1e-6:
                self._take_sample(s)
                self._applied_samples.add(k)
        if self.schedule.abort_at_s is not None and not self._abort_applied and self.schedule.abort_at_s <= t + 1e-6:
            self._apply_abort(t)

    def _take_sample(self, s):
        _, D = self._f(self.t, self.y, True)
        vals = {}
        for k in s.kinds:
            if k == "T":
                vals["T_K"] = D["T_bulk_K"]
            elif k in SI:
                vals[f"{k}_ppm"] = D[f"{k}_ladle_ppm"]
        self.lab_samples.append({"t_sample_s": self.t, "t_available_s": self.t + s.lab_delay_s, "values_truth": vals,
                                 "kinds": s.kinds})
        self._event("SAMPLE", f"sample taken ({', '.join(s.kinds)}); lab result due at {self.t + s.lab_delay_s:.0f} s")

    def _apply_abort(self, t):
        self._abort_applied = True
        # truncate schedule: vent 60 s, withdraw, dispatch
        keep = [ph for ph in self.phase_table if ph["t_start"] < t]
        cur = keep[-1]
        cur["t_end"] = t
        base = t
        new = [
            {"stage": "ABORT_VACUUM_BREAK", "duration_s": 60.0, "pressure_setpoint_Pa": self.P_atm,
             "pressure_setpoint_end_Pa": self.P_atm, "argon_NL_min": self.lim.argon_min_NL_min, "oxygen_Nm3_h": 0.0,
             "oxygen_ramp_s": 0.0, "vacuum_pump_on": False, "snorkels_immersed": True, "vent": True, "note": "abort"},
            {"stage": "DISPATCH", "duration_s": 600.0, "pressure_setpoint_Pa": self.P_atm,
             "pressure_setpoint_end_Pa": self.P_atm, "argon_NL_min": 0.0, "oxygen_Nm3_h": 0.0, "oxygen_ramp_s": 0.0,
             "vacuum_pump_on": False, "snorkels_immersed": False, "vent": False, "note": "abort dispatch"}]
        for i, d in enumerate(new):
            d.update({"index": len(keep) + i, "t_start": base, "t_end": base + d["duration_s"], "prev_o2": 0.0,
                      "blocked": False, "block_reason": None})
            base += d["duration_s"]
        self.phase_table = keep + new
        self.t_end_schedule = base
        # cancel all future additions and samples of the aborted schedule (logged, never silent)
        n_add = n_smp = 0
        for k, a in enumerate(self.schedule.additions):
            if k not in self._applied_additions:
                self._applied_additions.add(k)
                n_add += 1
        for k, smp in enumerate(self.schedule.samples):
            if k not in self._applied_samples:
                self._applied_samples.add(k)
                n_smp += 1
        if n_add or n_smp:
            self._event("ABORT_CANCELLED", f"{n_add} pending additions and {n_smp} pending samples cancelled", severity="warning")
        self._event("ABORT", "operator/scenario abort: oxygen OFF, vacuum break, withdrawal", severity="alarm")

    def step_to(self, t_target: float) -> dict:
        """Advance the simulation clock to t_target (bounded by schedule end)."""
        if self.status in ("failed", "completed"):
            return {"status": self.status}
        t_target = min(t_target, self.t_end_schedule)
        wall0 = _time.time()
        rec_dt = self.scfg.record_interval_s
        self.status = "running"
        atol = self._atol()
        while True:
            t_target = min(t_target, self.t_end_schedule)  # an abort can shorten the schedule
            if self.t >= t_target - 1e-9:
                break
            self._enter_phase(self.t)
            self._discrete_at(self.t)
            self._enter_phase(self.t)  # discrete events (abort) may have changed the phase table
            ph = self._ph
            seg_end = min(self.breakpoints(self.t, t_target)[0], ph["t_end"], t_target)
            if seg_end <= self.t + 1e-9:
                seg_end = min(self.t + 1e-3, t_target)
            n0 = math.floor(self.t / rec_dt + 1e-9) + 1
            t_eval = [k * rec_dt for k in range(n0, int(seg_end / rec_dt + 1e-9) + 1) if self.t < k * rec_dt <= seg_end + 1e-9]
            if not t_eval or abs(t_eval[-1] - seg_end) > 1e-9:
                t_eval.append(seg_end)
            try:
                sol = solve_ivp(self.rhs, (self.t, seg_end), self.y, method=self.scfg.method, t_eval=t_eval,
                                rtol=self.scfg.rtol, atol=atol, max_step=self.scfg.max_step_s)
            except Exception as exc:  # numerical exception -> robust failure result
                self.status = "failed"
                self._event("SOLVER_FAILURE", f"exception: {exc}", severity="alarm")
                self.solver_stats["failed_segments"] += 1
                break
            self.solver_stats["segments"] += 1
            self.solver_stats["nfev"] += int(sol.nfev)
            self.solver_stats["njev"] += int(getattr(sol, "njev", 0))
            self.solver_stats["nlu"] += int(getattr(sol, "nlu", 0))
            if not sol.success:
                self.status = "failed"
                self._event("SOLVER_FAILURE", f"solve_ivp: {sol.message}", severity="alarm")
                self.solver_stats["failed_segments"] += 1
                break
            for k, tk in enumerate(sol.t):
                yk = sol.y[:, k]
                self._check_negativity(tk, yk)
                if abs(tk - seg_end) < 1e-9:
                    self.t, self.y = float(tk), yk.copy()
                if abs(tk / rec_dt - round(tk / rec_dt)) < 1e-6 or abs(tk - seg_end) < 1e-9:
                    self._record(float(tk), yk)
            self.t, self.y = float(sol.t[-1]), sol.y[:, -1].copy()
            if _time.time() - wall0 > self.scfg.wall_time_budget_s:
                self.status = "failed"
                self._event("SOLVER_TIMEOUT", f"wall-time budget {self.scfg.wall_time_budget_s}s exceeded", severity="alarm")
                break
        if self.status == "running":
            self._enter_phase(self.t if self.t < self.t_end_schedule else self.t - 1e-6)
            self._discrete_at(self.t)
            self.status = "completed" if self.t >= self.t_end_schedule - 1e-6 else "paused"
            if not self.closure.ok:
                self.status = "failed"
                self._event("BALANCE_VIOLATION", self.closure.message(), severity="alarm")
        return {"status": self.status, "t_s": self.t}

    def run(self):
        return self.step_to(self.t_end_schedule)

    # ------------------------------------------------------------------ recording & checks
    def _check_negativity(self, t, y):
        L = self.L
        for z in self.zones:
            mz = y[L[f"m_{z}"]]
            if np.any(mz < -1e-5):
                k = int(np.argmin(mz))
                msg = f"negative inventory {SPECIES[k]} in zone {z}: {mz[k]:.3e} kg at t={t:.1f}s"
                if msg not in self.warnings:
                    self.warnings.append(msg)
                    self._event("NEGATIVITY", msg, severity="warning")

    def _record(self, t, y):
        if self._ph is None:
            self._ph = self.phase_at(t)
        _, D = self._f(t, y, True)
        L = self.L
        acc = y[L["acc_E"]]
        for k, name in enumerate(ENERGY_TERMS):
            D[f"E_{name}_MJ"] = acc[k] / 1e6
        D["cum_circulated_t"] = y[L["acc_circ"]] / 1000.0
        D["recirculation_number"] = y[L["acc_circ"]] / self.M0
        for k, s in enumerate(DC_SITES):
            D[f"cum_dC_{s}_kg"] = y[L["acc_dc"].start + k] * MW["C"]
        gi = y[L["acc_in"]]
        ge = y[L["acc_exh"]]
        D["cum_O2_Nm3"] = gi[GI["O2"]] * 0.022414
        D["cum_Ar_Nm3"] = (gi[GI["Ar"]]) * 0.022414
        for k, g in enumerate(GAS_SPECIES):
            D[f"cum_exh_{g}_kg"] = ge[k] * MW[g]
        D["cum_exhaust_kg"] = float(sum(ge[k] * MW[g] for k, g in enumerate(GAS_SPECIES)))
        res = self.closure.evaluate(t, y)
        D.update(res)
        D["Tw_ladle_K"] = y[L["Tw_ladle"]].tolist()
        D["Tw_vlow_K"] = y[L["Tw_vlow"]].tolist()
        D["Tw_vup_K"] = y[L["Tw_vup"]].tolist()
        D["stage_blocked"] = bool(self._ph["blocked"])
        self.records.append(_json_safe(D))


def liquidus_K(w: np.ndarray) -> float:
    """Empirical liquidus of low-alloy steel (wt%), commonly used in casting practice:
    T_liq[degC] = 1536 - (78 C + 7.6 Si + 4.9 Mn + 34 P + 30 S + 5 Cu + 3.1 Ni + 1.3 Cr + 3.6 Al
                   + 2 Mo + 2 V + 18 Ti)  -- illustrative; plants use their own formula."""
    p = w * 100.0
    dT = (78 * p[iC] + 7.6 * p[iSi] + 4.9 * p[iMn] + 34 * p[SI["P"]] + 30 * p[SI["S"]] + 5 * p[SI["Cu"]]
          + 3.1 * p[SI["Ni"]] + 1.3 * p[SI["Cr"]] + 3.6 * p[iAl] + 2 * p[SI["Mo"]] + 2 * p[SI["V"]] + 18 * p[iTi])
    return 1536.0 - dT + 273.15


def _json_safe(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _json_safe(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [None if (isinstance(a, float) and not math.isfinite(a)) else (float(a) if isinstance(a, (np.floating,)) else a) for a in v]
        elif isinstance(v, (np.floating, float)):
            fv = float(v)
            out[k] = fv if math.isfinite(fv) else None
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        else:
            out[k] = v
    return out
