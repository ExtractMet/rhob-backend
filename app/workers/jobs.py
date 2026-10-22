"""Background jobs (optimization, scenario comparison, ensemble) on a bounded thread pool.

Long computations return 202 Accepted + job_id; clients poll GET /api/v1/optimizations/{job_id}
(or /api/v1/jobs/{job_id}). Results are persisted in the optimizations table. A Redis/RQ
queue can replace this pool in production (docs/ARCHITECTURE.md)."""
from __future__ import annotations

import copy
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from ..core.config import SYNTHETIC_BANNER
from ..data import repositories as repo

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rhob-job")
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def submit(kind: str, fn, sim_id: str = "") -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:10]}"
    with _LOCK:
        JOBS[job_id] = {"job_id": job_id, "kind": kind, "simulation_id": sim_id, "status": "queued", "progress": 0.0,
                        "message": "", "result": None, "submitted": time.time()}
    repo.save_optimization(job_id, sim_id, "queued", {})

    def progress(f, msg=""):
        JOBS[job_id]["progress"] = float(f)
        JOBS[job_id]["message"] = msg

    def run():
        JOBS[job_id]["status"] = "running"
        try:
            res = fn(progress)
            res = res if isinstance(res, dict) else {"result": res}
            res["banner"] = SYNTHETIC_BANNER
            JOBS[job_id].update({"status": "done", "progress": 1.0, "result": res})
            repo.save_optimization(job_id, sim_id, "done", _strip(res))
        except Exception as exc:
            JOBS[job_id].update({"status": "failed", "message": f"{exc}", "trace": traceback.format_exc()[-2000:]})
            repo.save_optimization(job_id, sim_id, "failed", {"error": str(exc)})

    POOL.submit(run)
    return job_id


def _strip(res):
    return res


def get(job_id: str):
    j = JOBS.get(job_id)
    if j is not None:
        return {k: v for k, v in j.items() if k != "trace"} | ({"trace": j["trace"]} if "trace" in j else {})
    row = repo.get_optimization(job_id)
    if row is None:
        return None
    return {"job_id": job_id, "status": row["status"], "progress": 1.0 if row["status"] == "done" else 0.0,
            "result": row["result"], "simulation_id": row["simulation_id"], "message": "restored from database"}
