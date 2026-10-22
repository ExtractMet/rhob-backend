"""Historian (PI-like) export reader for HISTORICAL_REPLAY: long-format CSV with columns
t_s, tag, value, unit, quality, source (see datasets/synthetic_live_trace.csv). Read-only."""
from __future__ import annotations

import csv
from pathlib import Path


def load_trace(path: str | Path) -> dict[str, list[tuple[float, float, str]]]:
    out: dict[str, list] = {}
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].startswith("#")]
    header = rows[0]
    for r in rows[1:]:
        d = dict(zip(header, r))
        try:
            out.setdefault(d["tag"], []).append((float(d["t_s"]), float(d["value"]), d.get("quality", "GOOD")))
        except ValueError:
            continue
    return out


def stale_tags(trace: dict, t_now: float, max_age_s: float) -> list[str]:
    return [tag for tag, vals in trace.items() if not vals or t_now - vals[-1][0] > max_age_s]
