"""Plant signal provenance contract (section 5 of the brief).

Every live value carries {value, unit, timestamp, source, quality, CI, model_version} and the
signal definition carries the provenance columns below. Used by the integration adapters and
the sensor tag template (config/sensor_tags_template.csv)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ValueClass = Literal["MEASURED", "LAB ANALYZED", "SOFT-SENSED", "PREDICTED", "USER-DEFINED", "ESTIMATED", "OPTIMIZED", "UNAVAILABLE"]


class SignalDefinition(BaseModel):
    tag: str
    label: str
    unit: str
    data_type: Literal["float", "int", "bool", "string"] = "float"
    source: str = Field(..., description="OPC-UA node id / LIMS field / CSV column")
    sample_period_s: float = 1.0
    physical_min: Optional[float] = None
    physical_max: Optional[float] = None
    missing_value_policy: Literal["hold_last", "mark_unavailable", "interpolate_short"] = "mark_unavailable"
    sign_convention: str = ""
    calibration_date: Optional[str] = None
    override_role: str = "ProcessEngineer"
    value_class: ValueClass = "MEASURED"


class SignalValue(BaseModel):
    value: Optional[float]
    unit: str
    timestamp_utc: str
    ingestion_utc: Optional[str] = None
    source: str
    quality: Literal["GOOD", "UNCERTAIN", "BAD", "STALE", "SYNTHETIC"] = "GOOD"
    value_class: ValueClass = "MEASURED"
    CI95: Optional[tuple[float, float]] = None
    model_version: Optional[str] = None
