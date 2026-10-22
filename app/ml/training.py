"""Training / validation of the residual model with leakage-safe, heat-level CHRONOLOGICAL
splits (train 70 % / validation 15 % / test 15 % by heat order; one row per heat so the
split is grouped by heat by construction), permutation importance and bootstrap CI of the
test MAE. Metrics are on SYNTHETIC data and say nothing about plant accuracy."""
from __future__ import annotations

import functools
import json

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.inspection import permutation_importance

from ..core.config import DATASET_DIR
from .features import FEATURE_NAMES, TARGETS
from .residual_model import NOT_FOR_PLANT, ResidualModel


def load_dataset(path=None) -> list[dict]:
    p = path or (DATASET_DIR / "synthetic_heats.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)["heats"]


def _xy(rows, target):
    X = np.array([[r[f] for f in FEATURE_NAMES] for r in rows], dtype=float)
    y = np.array([r[target] for r in rows], dtype=float)
    return X, y


def train(rows: list[dict] | None = None, seed: int = 7) -> tuple[ResidualModel, dict]:
    rows = sorted(rows or load_dataset(), key=lambda r: r["heat_index"])
    n = len(rows)
    i1, i2 = int(0.70 * n), int(0.85 * n)
    tr, va, te = rows[:i1], rows[i1:i2], rows[i2:]
    models = {}
    report = {"n_heats": n, "split": {"train": len(tr), "validation": len(va), "test": len(te)},
              "split_method": "chronological by heat_index (grouped by heat)", "label": NOT_FOR_PLANT, "targets": {}}
    rng = np.random.default_rng(seed)
    for tgt in TARGETS:
        Xtr, ytr = _xy(tr, tgt)
        Xva, yva = _xy(va, tgt)
        Xte, yte = _xy(te, tgt)
        params = dict(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, min_samples_leaf=5, random_state=seed)
        mid = GradientBoostingRegressor(loss="squared_error", **params).fit(Xtr, ytr)
        lo = GradientBoostingRegressor(loss="quantile", alpha=0.05, **params).fit(Xtr, ytr)
        hi = GradientBoostingRegressor(loss="quantile", alpha=0.95, **params).fit(Xtr, ytr)
        models[tgt] = {"mid": mid, "lo": lo, "hi": hi}
        pred = mid.predict(Xte)
        base_mae = float(np.mean(np.abs(yte)))  # physics-only residual (= error of uncorrected twin)
        mae = float(np.mean(np.abs(yte - pred)))
        boots = []
        for _ in range(300):
            idx = rng.integers(0, len(yte), len(yte))
            boots.append(np.mean(np.abs(yte[idx] - pred[idx])))
        cover = float(np.mean((yte >= lo.predict(Xte)) & (yte <= hi.predict(Xte))))
        pi = permutation_importance(mid, Xva, yva, n_repeats=8, random_state=seed)
        imp = sorted(zip(FEATURE_NAMES, pi.importances_mean.tolist()), key=lambda z: -z[1])
        adopted = mae < 0.9 * base_mae  # validation gate: hybrid must beat physics-only by >= 10 % on holdout
        models[tgt]["adopted"] = adopted
        report["targets"][tgt] = {"test_MAE_physics_only": base_mae, "test_MAE_hybrid": mae,
                                  "validation_gate": "PASSED - residual correction adopted (shadow)" if adopted else
                                  "FAILED - residual not learnable from available features; physics-only prediction kept",
                                  "test_MAE_hybrid_CI95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                                  "PI90_coverage_test": cover, "permutation_importance_validation": imp[:10]}
    meta = {"version": "residual-gbr-demo-1", "features": FEATURE_NAMES, "seed": seed, "train_heat_index_max": tr[-1]["heat_index"],
            "status": "shadow", "approved_by": None}
    report["meta"] = meta
    return ResidualModel(models, meta), report


@functools.lru_cache(maxsize=1)
def get_model():
    return train()
