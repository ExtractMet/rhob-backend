"""FastAPI application: RH-OB Process Control and Digital Twin backend.

Start (Render / local):  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .api.v1 import (routes_admin, routes_config, routes_estimation, routes_health, routes_heats, routes_live,
                     routes_optimization, routes_reports, routes_simulation)
from .core.config import APP_NAME, MODEL_VERSION, get_settings
from .core.errors import RHOBError, rhob_error_handler
from .core.logging import setup_logging
from .data.db import init_db
from .orchestration.scheduler import TICKER


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    init_db()
    TICKER.start()
    yield
    TICKER.stop()


app = FastAPI(
    title=APP_NAME,
    version=MODEL_VERSION,
    description=("Hybrid physics + data-analytics digital twin, process simulator and Level-2 ADVISORY system for "
                 "Ruhrstahl-Heraeus Oxygen Blowing (RH-OB) secondary steelmaking. Engineering demonstration "
                 "(maturity Gate A). NOT connected to plant controls; no endpoint commands plant equipment. "
                 "(c) Extractmet Private Limited."),
    lifespan=lifespan,
)
_s = get_settings()
if _s.allowed_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_s.allowed_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_exception_handler(RHOBError, rhob_error_handler)
for r in (routes_health, routes_config, routes_heats, routes_simulation, routes_live, routes_optimization,
          routes_estimation, routes_reports, routes_admin):
    app.include_router(r.router)


@app.get("/", include_in_schema=False)
def root():
    return {"app": APP_NAME, "docs": "/docs", "health": "/healthz", "metadata": "/api/v1/metadata"}
