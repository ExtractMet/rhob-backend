# RH-OB Digital Twin — Deployment Guide (GitHub × 2 + Render × 2, and on-premises)

Product: **RH-OB Process Control and Digital Twin** — Extractmet Private Limited · Release 1.0.0-demo · Maturity Gate A
(engineering demonstration; not connected to plant controls).

The release contains two independent repositories:

| Repository | What it is | Render service type | Start command |
|---|---|---|---|
| `rhob-backend` | FastAPI physics engine + REST/SSE API + database | **Web Service** (Python) | `./start.sh` → `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `rhob-frontend` | Python (FastAPI + Jinja2) server delivering the HTML/CSS/Three.js operator desk; proxies API calls server-to-server | **Web Service** (Python) — *not* a static site | `./start.sh` → `uvicorn app:app --host 0.0.0.0 --port $PORT` |

---

## 1. Prerequisites
* GitHub account (organisation recommended), Git ≥ 2.40.
* Render account (render.com). For a usable demo choose **Starter or Standard** instances (the stiff solver is CPU-bound; a free 0.1-CPU instance sleeps after inactivity, has an ephemeral disk and is ~10× slower).
* Local testing: Python 3.13, (optional) Docker 24+, Node 18+ only if you want to re-vendor three.js/plotly.

## 2. Run locally first (10 minutes)
```bash
unzip rhob-backend.zip -d rhob-backend && unzip rhob-frontend.zip -d rhob-frontend
# terminal 1 – backend
cd rhob-backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && python scripts/check_install.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
# terminal 2 – frontend
cd rhob-frontend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
API_BASE_URL=http://localhost:8000 uvicorn app:app --host 0.0.0.0 --port 8501
```
Open http://localhost:8501 → the first visit simulates demo heat S2 (≈15 s). Backend API docs: http://localhost:8000/docs.
Windows PowerShell: `$env:API_BASE_URL="http://localhost:8000"; uvicorn app:app --port 8501`.

Docker (both repos side by side): `cd rhob-backend && docker compose up --build` → frontend :8501, backend :8000, PostgreSQL.

## 3. Create the two GitHub repositories
```bash
# backend
cd rhob-backend
git init -b main && git add . && git commit -m "RH-OB backend 1.0.0-demo"
gh repo create <org>/rhob-backend --private --source . --push      # or create on github.com and:
# git remote add origin https://github.com/<org>/rhob-backend.git && git push -u origin main
# frontend
cd ../rhob-frontend
git init -b main && git add . && git commit -m "RH-OB frontend 1.0.0-demo"
gh repo create <org>/rhob-frontend --private --source . --push
```
GitHub Actions CI (`.github/workflows/ci.yml`) runs automatically in each repository.

## 4. Deploy the backend on Render
**Option A — Blueprint (recommended):** Render Dashboard → *New* → *Blueprint* → connect `<org>/rhob-backend` →
Render reads `render.yaml` and creates the web service **rhob-backend** and the PostgreSQL database **rhob-db**
(`DATABASE_URL` is wired automatically; `RHOB_TOKEN_SECRET` is generated). Click *Apply*.

**Option B — manual Web Service:** *New* → *Web Service* → repository `rhob-backend`
* Runtime: Python 3 · Build command: `pip install -r requirements.txt` · Start command: `./start.sh`
* Health check path: `/healthz` · Instance: Starter/Standard
* Environment: `PYTHON_VERSION=3.13.x` (any 3.13 release offered by Render), `RHOB_TOKEN_SECRET=<random 64 chars>`,
  `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `DATABASE_URL=<Render Postgres *internal* URL>` (create a database under *New → PostgreSQL*).
  Without `DATABASE_URL` the service uses SQLite on Render's **ephemeral** disk (data lost on redeploy/restart).

`start.sh` binds `0.0.0.0` and `$PORT` (Render default 10000) and runs `alembic upgrade head` when a PostgreSQL URL is set.

Verify (replace the URL):
```bash
curl https://rhob-backend-xxxx.onrender.com/healthz          # {"status":"ok",...}
curl https://rhob-backend-xxxx.onrender.com/readyz           # {"ready":true,"database":true,"ticker":true,...}
curl https://rhob-backend-xxxx.onrender.com/api/v1/config/grades | head -c 300
# OpenAPI: https://rhob-backend-xxxx.onrender.com/docs
```

## 5. Deploy the frontend on Render
Blueprint with `<org>/rhob-frontend` (creates **rhob-frontend**) — or manual Web Service:
* Build: `pip install -r requirements.txt && python scripts/build_component.py --check`
* Start: `./start.sh` · Health check: `/healthz`
* Environment: `API_BASE_URL=https://rhob-backend-xxxx.onrender.com` (**required**, no trailing slash),
  `FRONTEND_SESSION_SECRET=<random>`, `COOKIE_SECURE=true`, `DEMO_DEFAULT_ACCOUNT=engineer`, `API_TIMEOUT_S=300`,
  `PYTHON_VERSION=3.13.x`.

The browser talks only to the frontend; the frontend calls the backend server-to-server, so **CORS is not needed**
(leave `ALLOWED_ORIGINS` empty on the backend). Render supports long-lived HTTP responses, which the SSE live
stream uses.

## 6. Integration test after deployment
1. `https://rhob-frontend-xxxx.onrender.com/readyz` → `"backend":{"reachable":true,...}`.
2. Open the frontend → page **01 Operational Overview**: the first visit creates and runs scenario S2; tiles, schematic and trends appear; mass/energy closure ≈ 1e-13.
3. Page **02 3D RH-OB Plant**: rotate/zoom, cutaway, scrub the timeline (oxygen jets visible during OB_DECARB).
4. Page **03 Heat Setup** → *Validate inputs* → *Create & run heat* with a 200 t preset.
5. Control bar → *Play ×30*, *Pause*, *Resume*, *Apply lab result*, *Export report (HTML)*.
6. Page **12 Optimizer** → *Request optimization* (1–3 min on 1 CPU) → FEASIBLE_PLAN or NO_FEASIBLE_PLAN with reasons.
7. Page **11 What-if** → compare S1 vs S2 (background job).

Expected first-request latency on a sleeping free instance: 30–60 s (cold start) — use paid instances for demos.

## 7. Custom domain & HTTPS
Render → service → *Settings* → *Custom Domains* → add `twin.extractmet.com` (CNAME to the Render host). TLS
certificates are issued automatically. Update `API_BASE_URL` if the backend gets a custom domain too.

## 8. Common errors
| Symptom | Cause / fix |
|---|---|
| Frontend shows "backend unreachable" | `API_BASE_URL` missing/typo, backend sleeping or failed build → check backend logs and `/readyz` |
| 502 on long actions | increase `API_TIMEOUT_S`; use a paid instance; optimization runs as a job and is polled |
| Very slow simulation | BLAS oversubscription → ensure `OPENBLAS_NUM_THREADS=1`; free instance CPU too small |
| Data disappears after redeploy | SQLite on ephemeral disk → attach Render PostgreSQL (`DATABASE_URL`) |
| `ModuleNotFoundError` at build | wrong root directory — repository root must contain `requirements.txt` |
| 3D view blank | browser without WebGL → the page falls back to the 2D schematic; enable hardware acceleration |
| 403 on actions | demo role is Viewer → choose Operator/ProcessEngineer in the top bar |
| Python version build error | set `PYTHON_VERSION` to a 3.13 patch release available on Render (or use the Dockerfile with Render's Docker runtime) |

## 9. Production caveats (read before any plant use)
* Public-cloud deployment = demonstration / remote advisory only. Never treat Render availability as a safety function.
* Free-tier sleep and ephemeral storage are unacceptable for live plant use.
* Live plant connection requires the on-premises path (section 10), site OT approvals and Gates C–D.

## 10. On-premises / private-cloud deployment
* `docker compose up -d` (PostgreSQL + backend + frontend) on a hardened VM in the L3 / DMZ zone; or Kubernetes
  (one Deployment per repo, PostgreSQL operator, Ingress with corporate TLS, OIDC proxy in front of the frontend).
* Data in via read-only adapters behind a data diode / OT-approved edge gateway (`docs/OT_INTEGRATION.md`).
* Backups (pg_dump nightly + WAL), central logging (JSON logs → SIEM), patching, test environment, change control, rollback, DR.
* Replace demo auth with SSO/OIDC (`RHOB_DEMO_AUTH=false`), rotate secrets, enable `COOKIE_SECURE=true`.
* Complete site threat/risk assessment, firewall approval, HAZOP/MoC; IEC 62443 / ISA-95 principles (no compliance claimed without assessment).

## 11. Updating
Push to `main` → Render auto-deploys (autoDeploy: true). Database schema changes: add an Alembic revision in
`app/data/migrations/versions/`; `start.sh` applies it on PostgreSQL.
