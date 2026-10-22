"""Result contracts (responses are permissive 'extra=allow' wrappers around typed cores)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class StateValue(BaseModel):
    model_config = ConfigDict(extra="allow")
    value: Optional[float]
    unit: Optional[str] = None
    source: str
    provenance: Optional[str] = None


class SimulationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    simulation_id: str
    heat_id: str
    mode: str
    status: str
    sim_time_s: float
    quality: str
    state: dict[str, StateValue]
    mass_balance_relative_error: float
    energy_balance_relative_error: float
    warnings: list[str]
    model_version: str
    version: int


class TrajectoryOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    simulation_id: str
    kind: str
    n_total: int
    since_index: int
    records: list[dict[str, Any]]
    banner: str
