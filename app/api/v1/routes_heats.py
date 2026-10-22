from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...core.errors import NotFound
from ...core.jsonsafe import SafeJSONResponse
from ...core.security import Principal, current_principal, require
from ...data import repositories as repo
from ...schemas.heat import HeatCreate
from ...services.audit import record

router = APIRouter(prefix="/api/v1/heats", tags=["heats"], default_response_class=SafeJSONResponse)


@router.post("", status_code=201, summary="Register a heat (arrival data)")
def create_heat(body: HeatCreate, p: Principal = Depends(require("Operator"))):
    hid = repo.save_heat(body.plant_id, body.heat.heat_id, body.heat.grade_id, body.heat.model_dump(mode="json"), p.user, body.provenance)
    record(p, "HEAT_CREATE", body.heat.heat_id, provenance=body.provenance)
    return {"id": hid, "heat_id": body.heat.heat_id}


@router.get("", summary="List heats (paginated)")
def list_heats(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), p: Principal = Depends(current_principal)):
    return {"items": repo.list_heats(limit, offset), "limit": limit, "offset": offset}


@router.get("/{heat_id}", summary="Get a heat")
def get_heat(heat_id: str, p: Principal = Depends(current_principal)):
    h = repo.get_heat(heat_id)
    if h is None:
        raise NotFound(f"heat {heat_id} not found")
    return h
