from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.errors import ValidationFailed
from ...core.jsonsafe import SafeJSONResponse
from ...core.security import Principal, current_principal
from ...ml.drift import drift_report
from ...ml.features import FEATURES, provenance_check
from ...ml.training import get_model, load_dataset

router = APIRouter(prefix="/api/v1/ml", tags=["estimation & ML"], default_response_class=SafeJSONResponse)


@router.get("/model", summary="Residual ML reference model: validation report (synthetic data)")
def model_report(p: Principal = Depends(current_principal)):
    _, rep = get_model()
    return {"report": rep, "features": [{"name": n, "provenance": pv, "source": src} for n, pv, src in FEATURES]}


@router.post("/predict", summary="Hybrid physics + ML endpoint correction for one heat feature row")
def predict(row: dict, p: Principal = Depends(current_principal)):
    bad = provenance_check(row)
    if bad:
        raise ValidationFailed("feature provenance check failed", {"missing_or_invalid": bad})
    m, _ = get_model()
    return m.predict(row)


@router.get("/dataset", summary="Synthetic heat dataset used for ML demonstration")
def dataset(limit: int = 200, p: Principal = Depends(current_principal)):
    rows = load_dataset()
    m, rep = get_model()
    out = []
    for r in rows[:limit]:
        pr = m.predict(r)
        out.append({**r, "hybrid_C_ppm": pr["C_corrected_ppm"], "hybrid_C_lo": pr["C_lo_ppm"], "hybrid_C_hi": pr["C_hi_ppm"],
                    "hybrid_T_K": pr["T_corrected_K"], "split": "train" if r["heat_index"] <= rep["meta"]["train_heat_index_max"] else "holdout"})
    return {"rows": out, "banner": "SYNTHETIC DATA"}


@router.get("/drift", summary="Feature drift (PSI) of the latest heats vs the training window")
def drift(p: Principal = Depends(current_principal)):
    rows = sorted(load_dataset(), key=lambda r: r["heat_index"])
    n = len(rows)
    return drift_report(rows[: int(0.7 * n)], rows[int(0.85 * n):])
