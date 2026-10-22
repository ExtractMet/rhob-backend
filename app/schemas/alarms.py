"""Alarm contract."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AlarmOut(BaseModel):
    t_s: float
    id: str
    name: Optional[str] = None
    severity: str
    message: str
    manual_response: Optional[str] = None
    interlock_owner: Optional[str] = None
    inhibit: Optional[str] = None
    simulated: bool = True


class AlarmAck(BaseModel):
    simulation_id: str
    hazard_id: str
    t_s: float
    comment: str = ""
