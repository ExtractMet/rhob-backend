"""Hybrid physics + ML residual correction (DEMONSTRATION ONLY - trained on synthetic data).

prediction = physics twin endpoint  (+) ML residual, then PHYSICS PROJECTION:
   C_corr = C_twin * exp(r_lnC), bounded to [C_eq_floor, 3 C_twin]   (positivity, plausibility)
   T_corr = T_twin + r_T, |r_T| <= 25 K
Uncertainty: quantile gradient boosting (5 % / 95 %) on the residuals.
Model replacement in production requires human approval and shadow A/B evaluation
(ModelVersion table status 'shadow' -> 'approved').
"""
from __future__ import annotations

import math

import numpy as np

from .features import FEATURE_NAMES

NOT_FOR_PLANT = "Synthetic-data reference model for software demonstration only - NOT for plant deployment."


class ResidualModel:
    def __init__(self, models: dict, meta: dict):
        self.models = models
        self.meta = meta

    def predict(self, row: dict) -> dict:
        X = np.array([[row[f] for f in FEATURE_NAMES]], dtype=float)
        rC = float(self.models["resid_lnC"]["mid"].predict(X)[0])
        rC_lo = float(self.models["resid_lnC"]["lo"].predict(X)[0])
        rC_hi = float(self.models["resid_lnC"]["hi"].predict(X)[0])
        rT = float(self.models["resid_T_K"]["mid"].predict(X)[0])
        rT_lo = float(self.models["resid_T_K"]["lo"].predict(X)[0])
        rT_hi = float(self.models["resid_T_K"]["hi"].predict(X)[0])
        C = row["twin_C_end_ppm"]
        T = row["twin_T_end_K"]
        if not self.models["resid_lnC"].get("adopted", True):
            rC = rC_lo = rC_hi = 0.0
        if not self.models["resid_T_K"].get("adopted", True):
            rT = rT_lo = rT_hi = 0.0
        proj = []

        def projC(r):
            v = C * math.exp(r)
            v2 = min(max(v, 0.5), 3 * C)
            if v2 != v:
                proj.append("C bounded")
            return v2

        def projT(r):
            r2 = max(min(r, 25.0), -25.0)
            if r2 != r:
                proj.append("T residual bounded")
            return T + r2

        return {"C_corrected_ppm": projC(rC), "C_lo_ppm": projC(min(rC_lo, rC)), "C_hi_ppm": projC(max(rC_hi, rC)),
                "T_corrected_K": projT(rT), "T_lo_K": projT(min(rT_lo, rT)), "T_hi_K": projT(max(rT_hi, rT)),
                "physics_C_ppm": C, "physics_T_K": T, "projection_events": proj, "label": NOT_FOR_PLANT,
                "model_version": self.meta.get("version"),
                "adopted": {k: bool(v.get("adopted", True)) for k, v in self.models.items()}}
