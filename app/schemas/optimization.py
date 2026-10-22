"""Optimization job contract."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class OptimizationStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    simulation_id: Optional[str] = None
    status: str  # queued | running | done | failed
    progress: float = 0.0
    message: str = ""
    result: Optional[dict[str, Any]] = None
