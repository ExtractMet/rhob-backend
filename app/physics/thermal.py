"""Refractory walls: 1-D radial transient conduction (finite volume, method of lines) with
coupled convection + radiation boundary conditions.

Each wall system (ladle, lower vessel+snorkels, upper vessel) is a set of concentric
cylindrical layers. Nodes are placed per layer; node temperatures are ODE states.
    rho_k cp_k V_k dT_k/dt = G_(k-1,k)(T_(k-1) - T_k) - G_(k,k+1)(T_k - T_(k+1))
Conductances between node centres use series cylindrical resistances
    R = ln(r_out/r_in)/(2 pi k L)   (scaled to the specified inner area).
Hot-face boundary: q_in = h_in A_in (T_steel - T_1)          (wetted walls)
                   or q_rad = sigma eps A (T_bath^4 - T_1^4)  (freeboard walls)
Cold-face boundary: q_out = A_out [h_conv (T_N - T_amb) + eps sigma (T_N^4 - T_amb^4)]
Stored energy E = sum rho cp V (T - 298.15) is exact for constant cp (closure check).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.units import SIGMA_SB
from .properties import REFRACTORY_LIBRARY


@dataclass
class WallSystem:
    name: str
    n: int
    C: np.ndarray       # heat capacity per node J/K
    G: np.ndarray       # conductance between node k and k+1, W/K (length n-1)
    G_in: float         # conductance hot face surface -> node 0 centre (W/K)
    G_out: float        # conductance node n-1 centre -> cold face (W/K)
    A_in: float
    A_out: float
    k_node: np.ndarray
    material: list
    r_nodes: np.ndarray  # node radii from inner surface
    Tmax: np.ndarray

    def stored_energy(self, T: np.ndarray) -> float:
        return float(np.dot(self.C, T - 298.15))


def build_wall(name: str, layers: list, r_inner: float, height: float, A_inner_target: float,
               nodes_working: int = 4) -> WallSystem:
    """Cylindrical wall of height ``height`` scaled so the inner area equals A_inner_target
    (bottom / end areas folded in via the scaling factor)."""
    A_cyl = 2 * math.pi * r_inner * height
    scale = A_inner_target / A_cyl if A_cyl > 0 else 1.0
    radii = []  # (r_in, r_out, props)
    mats = []
    r = r_inner
    for i, lay in enumerate(layers):
        props = REFRACTORY_LIBRARY[lay["material"] if isinstance(lay, dict) else lay.material]
        th = lay["thickness_m"] if isinstance(lay, dict) else lay.thickness_m
        nn = nodes_working if i == 0 else (2 if th > 0.05 else 1)
        dr = th / nn
        for j in range(nn):
            radii.append((r + j * dr, r + (j + 1) * dr, props))
            mats.append(lay["material"] if isinstance(lay, dict) else lay.material)
        r += th
    n = len(radii)
    C = np.zeros(n)
    k_node = np.zeros(n)
    Tmax = np.zeros(n)
    r_c = np.zeros(n)
    for i, (ri, ro, p) in enumerate(radii):
        V = math.pi * (ro ** 2 - ri ** 2) * height * scale
        C[i] = p["rho"] * p["cp"] * V
        k_node[i] = p["k"]
        Tmax[i] = p["Tmax"]
        r_c[i] = 0.5 * (ri + ro)

    def R_cyl(r1, r2, k):
        return math.log(r2 / r1) / (2 * math.pi * k * height * scale)

    G = np.zeros(max(n - 1, 0))
    for i in range(n - 1):
        ri, ro, p = radii[i]
        rj_i, rj_o, pj = radii[i + 1]
        R = R_cyl(r_c[i], ro, p["k"]) + R_cyl(rj_i, r_c[i + 1], pj["k"])
        G[i] = 1.0 / R
    G_in = 1.0 / R_cyl(radii[0][0], r_c[0], radii[0][2]["k"])
    G_out = 1.0 / R_cyl(r_c[-1], radii[-1][1], radii[-1][2]["k"])
    A_in = A_inner_target
    A_out = 2 * math.pi * radii[-1][1] * height * scale
    return WallSystem(name, n, C, G, G_in, G_out, A_in, A_out, k_node, mats, r_c - r_inner, Tmax)


def initial_profile(wall: WallSystem, T_hot: float, T_cold: float) -> np.ndarray:
    """Steady-conduction-like profile between hot face and shell (resistance weighted)."""
    R = np.concatenate([[1.0 / wall.G_in], 1.0 / wall.G, [1.0 / wall.G_out]])
    cum = np.cumsum(R)[:-1] / np.sum(R)
    return T_hot - (T_hot - T_cold) * cum


def surface_temperature_inner(wall: WallSystem, T0: float, q_in: float) -> float:
    return T0 + q_in / wall.G_in


def shell_loss(wall: WallSystem, T_last: float, h_conv: float, eps: float, T_amb: float) -> tuple[float, float]:
    """Heat loss [W] from the cold face, solved for the shell surface temperature with one
    Newton iteration on G_out (T_last - Ts) = A [h (Ts - Ta) + eps sigma (Ts^4 - Ta^4)]."""
    A = wall.A_out
    Ts = T_last
    for _ in range(4):
        f = wall.G_out * (T_last - Ts) - A * (h_conv * (Ts - T_amb) + eps * SIGMA_SB * (Ts ** 4 - T_amb ** 4))
        df = -wall.G_out - A * (h_conv + 4 * eps * SIGMA_SB * Ts ** 3)
        Ts = Ts - f / df
    q = wall.G_out * (T_last - Ts)
    return q, Ts


def wall_derivatives(wall: WallSystem, T: np.ndarray, q_in_to_node0: float, q_out: float) -> np.ndarray:
    dT = np.zeros(wall.n)
    flux = wall.G * (T[:-1] - T[1:])  # W from k to k+1
    dT[0] += q_in_to_node0
    dT[:-1] -= flux
    dT[1:] += flux
    dT[-1] -= q_out
    return dT / wall.C


def wetted_heat_flow(wall: WallSystem, T_fluid: float, T0: float, h_in: float) -> float:
    """Heat flow [W] steel -> node 0 with series film + half-node resistance."""
    R = 1.0 / (h_in * wall.A_in) + 1.0 / wall.G_in
    return (T_fluid - T0) / R


def radiative_heat_flow(wall: WallSystem, T_bath: float, A_bath: float, eps_bath: float, T0: float,
                        eps_wall: float = 0.8) -> tuple[float, float]:
    """Net radiation bath surface -> enclosing freeboard wall (two-surface enclosure),
    linearized around the wall surface with the node conduction resistance."""
    eps_eff = 1.0 / (1.0 / eps_bath + (A_bath / wall.A_in) * (1.0 / eps_wall - 1.0))
    # solve for surface temperature Ts: sigma eps_eff A_b (Tb^4 - Ts^4) = G_in (Ts - T0)
    Ts = T0
    for _ in range(5):
        f = SIGMA_SB * eps_eff * A_bath * (T_bath ** 4 - Ts ** 4) - wall.G_in * (Ts - T0)
        df = -4 * SIGMA_SB * eps_eff * A_bath * Ts ** 3 - wall.G_in
        Ts -= f / df
    return wall.G_in * (Ts - T0), Ts
