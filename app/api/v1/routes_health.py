from __future__ import annotations

import platform
import time

from fastapi import APIRouter

from ...core.config import (API_VERSION, APP_NAME, MATURITY_GATE, MODEL_VERSION, SYNTHETIC_BANNER, get_settings,
                            grades_version, source_hash)
from ...core.jsonsafe import SafeJSONResponse
from ...data.db import db_ok
from ...orchestration.scheduler import TICKER
from ...orchestration.simulation_runner import MANAGER

router = APIRouter(default_response_class=SafeJSONResponse)
STARTED = time.time()


@router.get("/healthz", tags=["health"], summary="Liveness probe")
def healthz():
    return {"status": "ok", "uptime_s": time.time() - STARTED}


@router.get("/readyz", tags=["health"], summary="Readiness: database reachable, physics core importable, ticker alive")
def readyz():
    ok_db = db_ok()
    ticker = TICKER.thread is not None and TICKER.thread.is_alive()
    ready = ok_db and ticker
    return SafeJSONResponse({"ready": ready, "database": ok_db, "ticker": ticker, "sessions": len(MANAGER.sessions)},
                            status_code=200 if ready else 503)


@router.get("/api/v1/metadata", tags=["health"], summary="Versions, mode boundary and maturity gate")
def metadata():
    s = get_settings()
    return {"app": APP_NAME, "api_version": API_VERSION, "model_version": MODEL_VERSION, "grades_version": grades_version(),
            "source_hash": source_hash()[:16], "git_sha": s.git_sha, "python": platform.python_version(), "env": s.env,
            "maturity_gate": MATURITY_GATE, "banner": SYNTHETIC_BANNER,
            "safety_boundary": "Engineering demonstration / remote advisory only. NOT a safety-rated controller. "
                               "No endpoint commands plant equipment. DCS/PLC own all interlocks.",
            "closed_loop_feature_enabled": s.closed_loop_feature,
            "modes": ["DEMO_SYNTHETIC", "ENGINEERING_BATCH_SIMULATION", "WHAT_IF", "HISTORICAL_REPLAY", "SHADOW_ONLINE",
                      "OPERATOR_ADVISORY", "APPROVED_CLOSED_LOOP_EDGE_ONLY (disabled)"]}
