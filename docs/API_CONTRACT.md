# API contract (v1) — full OpenAPI at `/docs` and `/openapi.json`

Base: `https://<backend>/`. JSON never contains NaN/Infinity (→ null). Errors: `{type, title, status, details}`.
Auth: `Authorization: Bearer <token>` (demo: `POST /api/v1/auth/demo-login {"account": "operator"}`).
Roles: Viewer < Operator < Metallurgist < ProcessEngineer < Admin (enforced server-side).

| Method & path | Role | Notes |
|---|---|---|
| GET /healthz, /readyz | – | liveness / readiness (DB, ticker) |
| GET /api/v1/metadata | – | versions, maturity gate, safety boundary |
| GET /api/v1/config/{plant,grades,materials,refractories,thermo,schema,hazards,state-machine,scenarios,scenarios/{name}} | Viewer | `plant?capacity_t=200` → capacity preset |
| POST /api/v1/heats · GET /api/v1/heats[/{heat_id}] | Operator / Viewer | heat registry |
| POST /api/v1/simulations | Operator (ProcessEngineer for kinetic changes) | body `{scenario}` or `{request}`, `run_to_end`, `capacity_t`; `Idempotency-Key` header; 201 + ETag |
| POST /api/v1/simulations/validate | Viewer | schedule + validity-domain issues |
| GET /api/v1/simulations[?limit&offset&heat_id] | Viewer | paginated |
| GET /api/v1/simulations/{id}[?heavy=true] | Viewer | summary, KPIs, endpoint, alarms, advisories, reproducibility, ETag |
| POST /api/v1/simulations/{id}/step `{dt_s|to_s}` | Operator | `If-Match` optimistic concurrency → 412; paused → 409 |
| POST …/pause · …/resume `{speed}` · …/reset | Operator | pause freezes the simulation clock |
| GET …/trajectory?fields&since_index&stride&kind=twin|plant | Viewer | paginated records |
| POST …/lab-results `{t_sample_s, values, source}` · GET …/lab-results | Operator | delayed reconciliation; future sample → 422 |
| GET …/forecast · …/estimator · …/ledger · …/mixing · …/visual | Viewer | |
| POST …/ensemble?n=8 | Operator | **202** + job_id |
| POST /api/v1/scenarios/compare | Viewer | **202** + job_id |
| GET /api/v1/jobs/{job_id} | Viewer | poll |
| POST /api/v1/optimization `{simulation_id, budget_s, max_iter, from_start}` | Operator | **202** + job_id |
| GET /api/v1/optimizations/{job_id} | Viewer | poll |
| GET /api/v1/stream/{id} | Viewer | SSE: `id` = record index, `Last-Event-ID` resume, `event: status` with stale flag, `event: end` |
| GET /api/v1/alarms · POST /api/v1/alarms/ack · POST /api/v1/advice/decision | Viewer / Operator | decisions audited, no command issued |
| GET /api/v1/ml/{model,dataset,drift} · POST /api/v1/ml/predict | Viewer | synthetic, gated |
| GET /api/v1/reports/{heat_id}?format=json|csv|html&simulation_id | Viewer | banner on every export |
| GET /api/v1/audit | Metallurgist | |
| GET/DELETE /api/v1/admin/sessions | ProcessEngineer / Admin | |
| GET /api/v1/live/sources | Viewer | adapter status (read-only) |

Example response fragment (illustrative values):
```json
{"simulation_id":"sim-1a2b3c4d5e","heat_id":"SYN-S2","mode":"DEMO_SYNTHETIC","status":"completed","sim_time_s":3060,
 "quality":"synthetic_valid","state":{"temperature_K":{"value":1868.2,"unit":"K","source":"model","provenance":"PREDICTED"}},
 "mass_balance_relative_error":2.8e-13,"energy_balance_relative_error":1.4e-15,
 "warnings":["SYNTHETIC DATA - ENGINEERING DEMONSTRATION - NOT VALIDATED FOR PLANT OPERATION - NOT CONNECTED TO PLANT CONTROLS"],
 "model_version":"1.0.0-demo"}
```
