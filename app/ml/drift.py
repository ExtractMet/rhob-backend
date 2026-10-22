"""Feature drift monitoring: Population Stability Index (PSI) per feature between the
training window and a recent window. PSI > 0.25 = significant drift -> flag model for
re-validation (no automatic replacement)."""
from __future__ import annotations

import numpy as np

from .features import FEATURE_NAMES


def psi(expected: np.ndarray, actual: np.ndarray, bins: int | None = None) -> float:
    if bins is None:  # small-sample guard: >= ~5 recent heats per bin
        bins = int(min(10, max(3, len(actual) // 5)))
    q = np.quantile(expected, np.linspace(0, 1, bins + 1))
    q[0], q[-1] = -np.inf, np.inf
    q = np.unique(q)
    # additive (Laplace) smoothing instead of clipping -> finite, less noisy for small windows
    ce = np.histogram(expected, q)[0] + 0.5
    ca = np.histogram(actual, q)[0] + 0.5
    e = ce / ce.sum()
    a = ca / ca.sum()
    return float(np.sum((a - e) * np.log(a / e)))


def drift_report(train_rows: list[dict], recent_rows: list[dict]) -> dict:
    out = {}
    for f in FEATURE_NAMES:
        e = np.array([r[f] for r in train_rows], dtype=float)
        a = np.array([r[f] for r in recent_rows], dtype=float)
        v = psi(e, a)
        out[f] = {"psi": v, "status": "drift" if v > 0.25 else ("watch" if v > 0.1 else "stable")}
    return {"features": out, "n_train": len(train_rows), "n_recent": len(recent_rows),
            "note": "small recent window -> PSI has high sampling variance; interpret 'watch' cautiously",
            "any_drift": any(v["status"] == "drift" for v in out.values()),
            "action": "re-validate in shadow mode; human approval required before replacement"}
