# rhob-backend — RH-OB Process Control and Digital Twin (FastAPI)

Hybrid physics + data-analytics digital twin, process simulator and Level-2 **advisory** system for
Ruhrstahl–Heraeus Oxygen Blowing (RH-OB) secondary steelmaking — **Extractmet Private Limited**.
Maturity **Gate A** (software complete, synthetic data). Not a safety-rated controller; no plant command path.

Frontend repository: <https://github.com/<org>/rhob-frontend> (Python + CSS + Three.js operator desk).

## Features
* Coupled dynamic model (solve_ivp BDF): two/three-zone steel, barometric hold-up, Kuwabara/energy-balance circulation,
  multi-site mixed-control decarburization, RH-OB oxygen jet with elemental O partition, FeO pool, post-combustion,
  H & N (Sieverts, poisoned 2nd-order N), dynamic vacuum gas phase with ejector curve, refractory conduction +
  convection + radiation, slag reoxidation, alloy dissolution & yield, O-probe deoxidation, Al₂O₃ inclusion classes.
* Element (19 elements) and energy closure at every record; runs fail on balance violation.
* Guarded state machine (O₂ permissives with reason codes), hazard registry, simulated interlocks.
* EKF soft sensor, delayed lab reconciliation, prediction bands, ensembles, hybrid ML with validation gates, drift.
* Lexicographic constrained optimizer (feasibility → economics), sensitivity, advisory cards, infeasibility reasons.
* 8 synthetic scenarios, capacity presets 100–350 t, SSE streaming, audit, roles, SQLite/PostgreSQL, Alembic.

## Quick start
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/check_install.py
uvicorn app.main:app --host 0.0.0.0 --port 8000      # OpenAPI at http://localhost:8000/docs
python scripts/simulate_example.py S2_RHOB_OXYGEN_ASSISTED --csv s2.csv
pip install -r requirements-dev.txt && pytest -q      # ~5 min
```
Docker: `docker compose up --build` (PostgreSQL + backend + ../rhob-frontend).
Render: `render.yaml` Blueprint (web service + PostgreSQL); start `./start.sh` (binds 0.0.0.0:$PORT).

## Documentation (`docs/`)
MODEL_EQUATIONS · MODEL_ASSUMPTIONS · ARCHITECTURE · API_CONTRACT · DATA_DICTIONARY · SOURCES · SAFETY_LIMITATIONS ·
VALIDATION_PLAN · OT_INTEGRATION · SECURITY · LIMITATIONS · MODEL_CARD · CHANGELOG · DEPLOYMENT_GUIDE.

© 2026 Extractmet Private Limited — see LICENSE.
