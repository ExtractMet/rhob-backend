from __future__ import annotations

from fastapi import APIRouter, Query

from ...core.config import grades_version, load_grades, load_yaml
from ...core.errors import NotFound
from ...core.jsonsafe import SafeJSONResponse
from ...physics import thermodynamics as td
from ...physics.alloying import materials_catalog
from ...physics.geometry import PRESET_CAPACITIES, derive, preset_for_capacity
from ...physics.properties import REFRACTORY_LIBRARY
from ...orchestration.scenarios import SCENARIO_DESCRIPTIONS, build_scenario
from ...orchestration.state_machine import ALLOWED_TRANSITIONS, REASON_CODES, STAGES
from ...schemas.configuration import GeometryConfig, PlantConfig, SimulationRequest
from ...services.alerts import HAZARDS

router = APIRouter(prefix="/api/v1/config", tags=["config"], default_response_class=SafeJSONResponse)


@router.get("/plant", summary="Default (demo) plant configuration with capacity presets")
def plant_config(capacity_t: float | None = Query(None, ge=60, le=420)):
    p = PlantConfig()
    if capacity_t is not None:
        p = PlantConfig(geometry=GeometryConfig.from_capacity(capacity_t))
        pre = preset_for_capacity(capacity_t)
        p.vacuum.pump_curve = pre["pump_curve"]
        p.limits.oxygen_max_Nm3_h = round(pre["oxygen_max_Nm3_h"])
        p.limits.argon_max_NL_min = round(1.3 * pre["argon_nominal_NL_min"])
    dg = derive(p.geometry.model_dump(), p.geometry.capacity_t * 1000)
    return {"plant": p.model_dump(mode="json"), "presets_t": PRESET_CAPACITIES,
            "derived_geometry": dg.__dict__, "label": "ILLUSTRATIVE demo configuration - replace with plant data at commissioning"}


@router.get("/grades", summary="Grade cards (illustrative)")
def grades():
    return {"version": grades_version(), "grades": [g.model_dump() for g in load_grades()]}


@router.get("/materials", summary="Addition material catalog (illustrative analyses)")
def materials():
    return materials_catalog()


@router.get("/refractories", summary="Refractory property library (illustrative)")
def refractories():
    return REFRACTORY_LIBRARY


@router.get("/thermo", summary="Thermochemical table at temperature T (K)")
def thermo(T: float = Query(1873.15, ge=1700, le=2100)):
    return {"T_K": T, "reactions": td.thermo_table(T), "sources": load_yaml("thermo_sources.yaml")}


@router.get("/schema", summary="JSON schema of SimulationRequest with unit/bounds/provenance metadata")
def schema():
    return SimulationRequest.model_json_schema()


@router.get("/hazards", summary="Hazard and operating-limit registry")
def hazards():
    return HAZARDS


@router.get("/state-machine", summary="Stages, allowed transitions, guard reason codes")
def state_machine():
    return {"stages": STAGES, "allowed_transitions": {str(k): sorted(v) for k, v in ALLOWED_TRANSITIONS.items()},
            "reason_codes": REASON_CODES}


@router.get("/scenarios", summary="Synthetic demonstration scenarios")
def scenarios():
    return SCENARIO_DESCRIPTIONS


@router.get("/scenarios/{name}", summary="Full typed request of a synthetic scenario")
def scenario(name: str):
    if name not in SCENARIO_DESCRIPTIONS:
        raise NotFound(f"unknown scenario {name}")
    return build_scenario(name).model_dump(mode="json")
