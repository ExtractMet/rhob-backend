"""CSV / Excel import-export of heats and lab results with schema validation (pandas)."""
from __future__ import annotations

import io

import pandas as pd

from ..schemas.configuration import HeatInput

HEAT_COLUMNS = ["heat_id", "grade_id", "steel_mass_t", "T_arrival_K", "C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "S", "P",
                "Cr", "Ni", "Nb", "V", "Cu", "Mo", "slag_mass_t"]


def heats_from_table(data: bytes, filename: str) -> tuple[list[HeatInput], list[str]]:
    """Parse a CSV/XLSX heat table; returns (valid heats, error messages). Invalid rows are
    rejected with a reason - never silently coerced."""
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(data))
    else:
        df = pd.read_csv(io.BytesIO(data), comment="#")
    missing = [c for c in ["heat_id", "grade_id", "steel_mass_t", "T_arrival_K", "C", "O"] if c not in df.columns]
    if missing:
        return [], [f"missing required columns: {missing}"]
    heats, errors = [], []
    for i, row in df.iterrows():
        try:
            comp = {k: float(row[k]) for k in ["C", "O", "H", "N", "Al", "Si", "Mn", "Ti", "S", "P", "Cr", "Ni", "Nb", "V", "Cu", "Mo"]
                    if k in df.columns and pd.notna(row[k])}
            h = HeatInput(heat_id=str(row["heat_id"]), grade_id=str(row["grade_id"]), steel_mass_t=float(row["steel_mass_t"]),
                          T_arrival_K=float(row["T_arrival_K"]), composition_ppm={**HeatInput().composition_ppm, **comp},
                          slag_mass_t=float(row["slag_mass_t"]) if "slag_mass_t" in df.columns and pd.notna(row["slag_mass_t"]) else 3.5)
            heats.append(h)
        except Exception as exc:
            errors.append(f"row {i}: {exc}")
    return heats, errors


def records_to_csv(records: list[dict], banner: str) -> str:
    keys = [k for k, v in records[0].items() if not isinstance(v, (dict, list))]
    df = pd.DataFrame([{k: r.get(k) for k in keys} for r in records])
    return f"# {banner}\n" + df.to_csv(index=False)
