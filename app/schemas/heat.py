"""Heat records API contract."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from .configuration import HeatInput


class HeatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plant_id: str = "INDUSTRY-X"
    heat: HeatInput
    provenance: str = "USER-DEFINED"
    note: Optional[str] = None


class HeatOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    heat_id: str
    plant_id: str
    grade_id: str
    payload: dict
    provenance: str
