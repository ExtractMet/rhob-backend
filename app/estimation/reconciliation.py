"""Delayed laboratory reconciliation of the full twin state.

On arrival of a lab result taken at t_s (now = t > t_s):
    innovation  nu = y_lab - y_model(t_s)          (model value interpolated from the record)
    gain        K  = s_m^2 / (s_m^2 + s_lab^2)     (scalar; s_m grows with time since last update)
    carry-forward to t:
        C, H, N   (first-order decay species): delta(t) = K nu (y(t) - y_eq) / (y(t_s) - y_eq)
        O, Al, Si, Mn, Ti, T (additive):        delta(t) = K nu
The correction is applied to every steel zone in proportion to its inventory (mass) or, for T,
to every zone enthalpy. Raw lab data are stored unchanged; the twin state change, gain and
pre/post forecast bias are logged.
"""
from __future__ import annotations

import numpy as np

from ..physics.properties import SPECIES, SPECIES_INDEX, steel_cp_liquid

LAB_SIGMA = {"C": 3.0, "O": 4.0, "H": 0.3, "N": 3.0, "Al": 15.0, "Si": 20.0, "Mn": 30.0, "Ti": 15.0, "T": 3.0}
MODEL_SIGMA_REL = {"C": 0.15, "O": 0.12, "H": 0.15, "N": 0.08, "Al": 0.06, "Si": 0.05, "Mn": 0.03, "Ti": 0.08}
MODEL_SIGMA_T0 = 4.0
DECAY = {"C", "H", "N"}


def interpolate_record(records: list, t: float, key: str):
    ts = np.array([r["t_s"] for r in records])
    vs = np.array([r.get(key) if r.get(key) is not None else np.nan for r in records], dtype=float)
    ok = ~np.isnan(vs)
    if not ok.any():
        return None
    return float(np.interp(t, ts[ok], vs[ok]))


def assimilate(model, kind: str, value: float, t_sample: float, sigma_lab: float | None = None) -> dict:
    recs = model.records
    key = "T_bulk_K" if kind == "T" else f"{kind}_bulk_ppm"
    y_ts = interpolate_record(recs, t_sample, key)
    if y_ts is None:
        return {"applied": False, "reason": "no model value at sample time"}
    _, D = model._f(model.t, model.y, True)
    y_now = D[key]
    s_lab = sigma_lab if sigma_lab is not None else LAB_SIGMA.get(kind, 5.0)
    if kind == "T":
        s_m = (MODEL_SIGMA_T0 ** 2 + (0.08 * (model.t - t_sample) / 60.0) ** 2) ** 0.5 + 2.0
    else:
        s_m = max(MODEL_SIGMA_REL.get(kind, 0.1) * max(abs(y_ts), 1.0), 0.5)
    K = s_m ** 2 / (s_m ** 2 + s_lab ** 2)
    nu = value - y_ts
    if kind in DECAY:
        eq = {"C": D.get("C_eq_surface_ppm") or 0.0, "H": D.get("H_eq_ppm") or 0.0, "N": D.get("N_eq_ppm") or 0.0}[kind]
        eq = min(eq, 0.5 * y_now)
        ratio = (y_now - eq) / (y_ts - eq) if abs(y_ts - eq) > 1e-9 else 1.0
        delta = K * nu * max(min(ratio, 1.0), 0.0)
    else:
        delta = K * nu
    L = model.L
    y = model.y
    if kind == "T":
        for z in model.zones:
            Mz = y[L[f"M_{z}"]]
            if Mz <= 1.0:
                continue
            cp = steel_cp_liquid(y[L[f"m_{z}"]] / Mz)
            y[L[f"H_{z}"]] += Mz * cp * delta
    else:
        i = SPECIES_INDEX[kind]
        new_now = max(y_now + delta, 0.0)
        for z in model.zones:
            Mz = y[L[f"M_{z}"]]
            if Mz <= 1.0:
                continue
            sl = L[f"m_{z}"]
            cur = y[sl.start + i]
            if kind in DECAY and y_now > 1e-9:
                y[sl.start + i] = cur * new_now / y_now
            else:
                y[sl.start + i] = max(cur + delta * 1e-6 * Mz, 0.0)
    # closure bookkeeping: an assimilation is an EXTERNAL correction - record it in the tracker
    model.closure_corrections = getattr(model, "closure_corrections", [])
    model.closure_corrections.append({"t_s": model.t, "kind": kind, "delta": delta})
    model.closure.rebase(model.y)
    entry = {"applied": True, "kind": kind, "t_sample_s": t_sample, "t_applied_s": model.t, "lab_value": value,
             "model_at_sample": y_ts, "innovation": nu, "gain": K, "model_sigma": s_m, "lab_sigma": s_lab,
             "model_now_before": y_now, "correction_now": delta, "model_now_after": y_now + delta}
    model._event("LAB_ASSIMILATION", f"{kind}: lab {value:.2f} vs model {y_ts:.2f} at {t_sample:.0f}s; "
                 f"gain {K:.2f}; state corrected by {delta:+.2f}", entry)
    model._record(model.t, model.y)
    return entry
