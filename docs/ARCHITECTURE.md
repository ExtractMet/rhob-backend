# Architecture — RH-OB Process Control and Digital Twin

```
 Browser (operator desk: HTML + CSS + Three.js + Plotly.js)
        │  HTTPS (session cookie; no API token in the browser)
        ▼
 rhob-frontend  (Python FastAPI + Jinja2; BFF proxy /bff/*, allow-listed)     ← GitHub repo #1, Render web service #1
        │  server-to-server HTTPS, Bearer token (role)
        ▼
 rhob-backend   (FastAPI, versioned REST /api/v1, SSE /api/v1/stream)        ← GitHub repo #2, Render web service #2
   ├─ physics/        first-principles engine (two/three-zone steel, vacuum gas, OB jet, H/N, thermal walls, inclusions, ledgers)
   ├─ orchestration/  state machine + guards, scenarios, simulation sessions (twin + synthetic plant), ticker
   ├─ estimation/     EKF soft sensor, delayed lab reconciliation, uncertainty bands, ensembles
   ├─ ml/             hybrid residual model (synthetic, gated), drift (PSI)
   ├─ optimization/   lexicographic constrained advisory optimizer (grid → COBYLA → FD sensitivity)
   ├─ services/       alarms/hazard registry, reporting/KPIs/advisory cards, audit, validation
   ├─ integrations/   READ-ONLY adapters: CSV/Excel, OPC UA, historian replay, LIMS, MQTT, synthetic
   ├─ data/           SQLAlchemy models, repositories, Alembic migrations (SQLite demo / PostgreSQL prod)
   └─ workers/        bounded thread pool for 202-Accepted jobs (optimization, compare, ensemble)
```

Key design decisions
* **Physics is the source of truth.** ML only corrects residuals that pass a holdout validation gate.
* **No plant command path.** No endpoint writes to equipment; adapters are read-only by construction.
* **Reproducibility.** Every simulation stores request, seed, config version, source hash, git SHA and result checksum.
* **Sessions survive restarts**: the request is persisted; a session is deterministically re-integrated on demand.
* **Concurrency**: one RLock per session; jobs snapshot (deep-copy) the twin before computing.
* **Frontend independence**: the frontend never imports backend Python; all calls cross the HTTP contract.

Mapping to the master brief's Streamlit layout: per the client's instruction the GUI is implemented as
**Python (FastAPI/Jinja2) + CSS + Three.js** instead of Streamlit; each brief page `pages/NN_*.py` maps to
`templates/<slug>.html` + `static/js/pages/<slug>.js` (16 pages, see the frontend README).
