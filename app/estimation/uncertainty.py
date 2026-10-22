"""Prediction-interval propagation.

1. ANALYTIC (fast, every record): first-order propagation for exponentially decaying species
   y(t) = y_eq + (y0 - y_eq) exp(-K t) with relative uncertainty s_K of the apparent rate
   constant (from circulation_multiplier_sd and mass-transfer uncertainty):
       s_ln(y - y_eq) = K * dt * s_K
   Temperature: s_T(t)^2 = s_T0^2 + (s_rate * dt)^2.
2. ENSEMBLE (on request): N twin runs with kinetic parameters sampled from their stated
   uncertainty (seeded) -> empirical 5/50/95 % bands.  Costlier; executed as a background job.
"""
from __future__ import annotations

import copy
import math

import numpy as np

S_RATE_T = 0.25 / 60.0  # K/s 1-sigma uncertainty of the thermal rate (uncalibrated)
S_T0 = 3.0


def analytic_bands(records: list, t_from: float, s_K: float = 0.22, z: float = 1.645) -> dict:
    out = {"t_s": [], "C_lo": [], "C_hi": [], "H_lo": [], "H_hi": [], "N_lo": [], "N_hi": [], "T_lo": [], "T_hi": []}
    base = None
    for r in records:
        if r["t_s"] < t_from:
            continue
        if base is None:
            base = r
        dt = r["t_s"] - t_from
        out["t_s"].append(r["t_s"])
        K = max((r.get("K_app_1_min") or 0.0) / 60.0, 0.0)
        for sp, eqk in [("C", "C_eq_surface_ppm"), ("H", "H_eq_ppm"), ("N", "N_eq_ppm")]:
            y = r.get(f"{sp}_bulk_ppm") or 0.0
            eq = min(r.get(eqk) or 0.0, 0.5 * y)
            Kx = K if sp == "C" else K * 0.6
            s = Kx * dt * s_K
            out[f"{sp}_lo"].append(eq + (y - eq) * math.exp(-z * s))
            out[f"{sp}_hi"].append(eq + (y - eq) * math.exp(z * s))
        sT = math.sqrt(S_T0 ** 2 + (S_RATE_T * dt) ** 2)
        T = r.get("T_bulk_K") or 0.0
        out["T_lo"].append(T - z * sT)
        out["T_hi"].append(T + z * sT)
    return out


def sample_kinetics(kin, rng: np.random.Generator) -> dict:
    return {
        "circulation_multiplier": float(kin.circulation_multiplier * np.exp(rng.normal(0, kin.circulation_multiplier_sd))),
        "k_C_surface_m_s": float(kin.k_C_surface_m_s * np.exp(rng.normal(0, 0.15))),
        "k_N_m_s": float(kin.k_N_m_s * np.exp(rng.normal(0, 0.2))),
        "k_H_m_s": float(kin.k_H_m_s * np.exp(rng.normal(0, 0.15))),
        "k_r0_N_mol_m2_s_atm": float(kin.k_r0_N_mol_m2_s_atm * np.exp(rng.normal(0, 0.3))),
        "bubble_equilibrium_approach": float(np.clip(kin.bubble_equilibrium_approach * np.exp(rng.normal(0, 0.2)), 0.05, 0.95)),
        "o2_absorption_lambda": float(kin.o2_absorption_lambda * np.exp(rng.normal(0, 0.2))),
    }


def ensemble(model_factory, n: int, seed: int, keys=("C_bulk_ppm", "T_bulk_K", "H_bulk_ppm", "N_bulk_ppm", "O_bulk_ppm")) -> dict:
    rng = np.random.default_rng(seed)
    runs = []
    for i in range(n):
        m = model_factory(rng)
        m.run()
        runs.append(m.records)
    t = [r["t_s"] for r in runs[0]]
    out = {"t_s": t, "n": n, "seed": seed}
    for k in keys:
        arr = np.array([[ (rr[j].get(k) if j < len(rr) and rr[j].get(k) is not None else np.nan) for j in range(len(t))] for rr in runs])
        out[k] = {"p05": np.nanpercentile(arr, 5, axis=0).tolist(), "p50": np.nanpercentile(arr, 50, axis=0).tolist(),
                  "p95": np.nanpercentile(arr, 95, axis=0).tolist()}
    return out
