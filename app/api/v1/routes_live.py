"""Server-Sent Events stream of trajectory records.

* id: record index -> clients reconnect with Last-Event-ID and receive only newer records
  (duplicates are impossible because ids are monotonic per simulation).
* heartbeat comment every 10 s; `event: status` carries stale-data flag (no new record for
  > 30 s while the session is playing) so the UI can show a stale banner.
* backpressure: at most `batch` records per message; the stream ends when the simulation is
  completed and all records are sent, or after max_s.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from ...core.jsonsafe import SafeJSONResponse, clean
from ...core.security import Principal, current_principal
from ...integrations.synthetic_source import adapter_status
from ...orchestration.simulation_runner import MANAGER

router = APIRouter(prefix="/api/v1", tags=["live"], default_response_class=SafeJSONResponse)

FIELDS = ["t_s", "stage", "P_Pa", "T_bulk_K", "C_bulk_ppm", "O_bulk_ppm", "H_bulk_ppm", "N_bulk_ppm", "Al_bulk_ppm",
          "q_circ_t_min", "argon_NL_min", "oxygen_Nm3_h", "offgas_CO_Nm3_h", "vessel_depth_m", "x_CO",
          "mass_balance_relative_error", "energy_balance_relative_error"]


@router.get("/stream/{sim_id}", summary="SSE stream of state packets (Last-Event-ID resume)")
async def stream(sim_id: str, request: Request, last_event_id: str | None = Header(default=None),
                 batch: int = Query(20, ge=1, le=200), max_s: float = Query(900, ge=5, le=3600),
                 p: Principal = Depends(current_principal)):
    s = MANAGER.get(sim_id)
    start = int(last_event_id) + 1 if (last_event_id and last_event_id.isdigit()) else 0

    async def gen():
        idx = start
        t0 = time.time()
        last_new = time.time()
        last_hb = 0.0
        yield "retry: 3000\n\n"
        while time.time() - t0 < max_s:
            if await request.is_disconnected():
                break
            recs = s.twin.records
            if idx < len(recs):
                chunk = recs[idx: idx + batch]
                for r in chunk:
                    data = json.dumps(clean({k: r.get(k) for k in FIELDS}), allow_nan=False)
                    yield f"id: {idx}\nevent: record\ndata: {data}\n\n"
                    idx += 1
                last_new = time.time()
            else:
                stale = s.playing and (time.time() - last_new) > 30
                if time.time() - last_hb > 10:
                    st = json.dumps({"status": s.status, "sim_time_s": s.t, "stale": stale})
                    yield f"event: status\ndata: {st}\n\n: keep-alive\n\n"
                    last_hb = time.time()
                if s.status in ("completed", "failed") and idx >= len(s.twin.records):
                    yield f"event: end\ndata: {json.dumps({'status': s.status})}\n\n"
                    break
                await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/live/sources", summary="Status of read-only data adapters (OPC UA / historian / LIMS / MQTT)")
def sources(p: Principal = Depends(current_principal)):
    return adapter_status()
