"""Mixing analysis of the zone network (ladle active / ladle dead / vessel).

For passive-tracer transport the zone network is linear: dc/dt = A c with
A built from circulation q_c and exchange q_ex. The slowest non-zero eigenvalue lambda_2
gives the 95 % mixing time  t95 = ln(20)/|lambda_2|. A residence-time / tracer response
curve (pulse into the vessel) is obtained by integrating the linear system with expm.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.linalg import expm


def transport_matrix(M_l: float, M_d: float, M_v: float, q_c: float, q_ex: float) -> np.ndarray:
    zones = [M_l, M_v] + ([M_d] if M_d > 0 else [])
    n = len(zones)
    A = np.zeros((n, n))
    # l <-> v circulation
    A[0, 0] -= q_c / M_l
    A[0, 1] += q_c / M_l
    A[1, 1] -= q_c / M_v
    A[1, 0] += q_c / M_v
    if n == 3:
        A[0, 0] -= q_ex / M_l
        A[0, 2] += q_ex / M_l
        A[2, 2] -= q_ex / M_d
        A[2, 0] += q_ex / M_d
    return A


def mixing_time_95(M_l, M_d, M_v, q_c, q_ex) -> float:
    if q_c <= 0 or M_v <= 0:
        return float("inf")
    A = transport_matrix(M_l, M_d, M_v, q_c, q_ex)
    ev = np.sort(np.abs(np.real(np.linalg.eigvals(A))))
    nonzero = ev[ev > 1e-12]
    if nonzero.size == 0:
        return float("inf")
    return math.log(20.0) / nonzero[0]


def tracer_response(M_l, M_d, M_v, q_c, q_ex, t_end: float = 600.0, n: int = 121) -> dict:
    """Pulse of tracer added to the vessel zone; normalized bulk-ladle concentration vs time."""
    if q_c <= 0 or M_v <= 0:
        return {"t_s": [], "ladle_norm": [], "vessel_norm": []}
    A = transport_matrix(M_l, M_d, M_v, q_c, q_ex)
    masses = np.array([M_l, M_v] + ([M_d] if M_d > 0 else []))
    c0 = np.zeros(len(masses))
    c0[1] = 1.0 / masses[1]  # 1 kg tracer in vessel
    c_inf = 1.0 / masses.sum()
    ts = np.linspace(0, t_end, n)
    lad, ves = [], []
    for t in ts:
        c = expm(A * t) @ c0
        if len(masses) == 3:
            cl = (c[0] * masses[0] + c[2] * masses[2]) / (masses[0] + masses[2])
        else:
            cl = c[0]
        lad.append(cl / c_inf)
        ves.append(c[1] / c_inf)
    return {"t_s": ts.tolist(), "ladle_norm": lad, "vessel_norm": ves}


def recirculation_number(cum_circulated_kg: float, M_total: float) -> float:
    return cum_circulated_kg / M_total if M_total > 0 else 0.0
