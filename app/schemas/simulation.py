"""API request/response contracts for simulations, lab results, optimization, comparisons."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .configuration import SimulationRequest


class SimulationCreate(BaseModel):
    """Create a simulation either from a full typed request or from a named synthetic scenario."""
    model_config = ConfigDict(extra="forbid")
    request: Optional[SimulationRequest] = None
    scenario: Optional[str] = Field(None, description="Synthetic scenario name, e.g. S2_RHOB_OXYGEN_ASSISTED")
    run_to_end: bool = Field(False, description="Integrate the full schedule immediately (synchronous, ~5-10 s)")
    capacity_t: Optional[float] = Field(None, ge=60, le=420, description="Apply the geometry preset for this ladle capacity")

    @model_validator(mode="after")
    def _one(self):
        if self.request is None and self.scenario is None:
            self.request = SimulationRequest()
        return self


class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dt_s: Optional[float] = Field(None, gt=0, le=7200)
    to_s: Optional[float] = Field(None, ge=0, le=20000)


class ResumeRequest(BaseModel):
    speed: float = Field(0.0, ge=0.0, le=200.0, description="0 = manual stepping; >0 = simulated s per wall s")


class LabResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t_sample_s: float = Field(..., ge=0)
    values: dict[str, float] = Field(..., description="e.g. {'C_ppm': 22.0, 'T_K': 1870.0}")
    source: Literal["LAB ANALYZED", "USER-DEFINED", "LAB ANALYZED (synthetic plant)", "MEASURED"] = "LAB ANALYZED"
    reason: str = ""


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[str] = Field(default_factory=list, max_length=6)
    requests: list[SimulationRequest] = Field(default_factory=list, max_length=6)
    simulation_ids: list[str] = Field(default_factory=list, max_length=6)


class OptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_id: str
    budget_s: float = Field(180.0, ge=20, le=900)
    from_start: Optional[bool] = Field(None, description="True: re-plan the whole heat from t=0; False: receding horizon from the "
                                       "current state; None: automatic (from start if the deep-vacuum phase is already over)")
    max_iter: int = Field(8, ge=2, le=40)


class JobAccepted(BaseModel):
    job_id: str
    status: str = "accepted"
    poll: str


class TrajectoryQuery(BaseModel):
    fields: Optional[list[str]] = None
    since_index: int = 0
    stride: int = 1
    kind: Literal["twin", "plant"] = "twin"


class Envelope(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: Any = None
