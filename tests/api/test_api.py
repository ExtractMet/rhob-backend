import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def token(c, acc):
    return {"Authorization": "Bearer " + c.post("/api/v1/auth/demo-login", json={"account": acc}).json()["token"]}


def test_health_and_metadata(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    md = client.get("/api/v1/metadata").json()
    assert md["maturity_gate"] == "A" and "NOT" in md["banner"]
    g = client.get("/api/v1/config/grades").json()
    assert any(x["grade_id"] == "IF-ULC" for x in g["grades"])
    assert client.get("/api/v1/config/plant", params={"capacity_t": 200}).json()["plant"]["geometry"]["capacity_t"] == 200


def test_roles_enforced_in_backend(client):
    r = client.post("/api/v1/simulations", json={"scenario": "S1_RH_BASELINE_O2_OFF"}, headers=token(client, "viewer"))
    assert r.status_code == 403
    r = client.get("/api/v1/audit", headers=token(client, "operator"))
    assert r.status_code == 403


def test_simulation_lifecycle(client):
    h = token(client, "operator")
    r = client.post("/api/v1/simulations", json={"scenario": "S1_RH_BASELINE_O2_OFF"}, headers={**h, "Idempotency-Key": "k-123"})
    assert r.status_code == 201
    sim = r.json()["simulation_id"]
    r2 = client.post("/api/v1/simulations", json={"scenario": "S1_RH_BASELINE_O2_OFF"}, headers={**h, "Idempotency-Key": "k-123"})
    assert r2.json()["simulation_id"] == sim  # idempotent replay
    s = client.post(f"/api/v1/simulations/{sim}/step", json={"to_s": 1400}, headers=h).json()
    assert s["sim_time_s"] == pytest.approx(1400)
    raw = client.get(f"/api/v1/simulations/{sim}").text
    assert "NaN" not in raw and "Infinity" not in raw
    etag = client.get(f"/api/v1/simulations/{sim}").headers["etag"]
    assert client.post(f"/api/v1/simulations/{sim}/step", json={"dt_s": 10}, headers={**h, "If-Match": 'W/"stale"'}).status_code == 412
    assert client.post(f"/api/v1/simulations/{sim}/pause", headers=h).status_code == 200
    assert client.post(f"/api/v1/simulations/{sim}/step", json={"dt_s": 10}, headers=h).status_code == 409
    assert client.post(f"/api/v1/simulations/{sim}/resume", json={"speed": 0}, headers=h).status_code == 200
    tr = client.get(f"/api/v1/simulations/{sim}/trajectory", params={"fields": "C_bulk_ppm,T_bulk_K", "stride": 5}).json()
    assert tr["records"] and set(tr["records"][0]) == {"t_s", "stage", "C_bulk_ppm", "T_bulk_K"}
    labs = client.get(f"/api/v1/simulations/{sim}/lab-results").json()["items"]
    avail = [l for l in labs if l["available"]]
    rec = client.post(f"/api/v1/simulations/{sim}/lab-results", json={"t_sample_s": avail[-1]["t_sample_s"], "values": {"C_ppm": 30.0}}, headers=h)
    assert rec.status_code == 200 and rec.json()["entries"][0]["applied"]
    assert client.post(f"/api/v1/simulations/{sim}/lab-results", json={"t_sample_s": 99999, "values": {"C_ppm": 30.0}}, headers=h).status_code == 422
    assert client.post(f"/api/v1/simulations/{sim}/lab-results", json={"t_sample_s": 10, "values": {"C_ppm": -3}}, headers=h).status_code == 422
    fc = client.get(f"/api/v1/simulations/{sim}/forecast").json()
    assert fc["endpoint"]["checks"]
    assert client.get(f"/api/v1/simulations/{sim}/ledger").json()["closure_ok"]
    assert client.get(f"/api/v1/simulations/{sim}/visual").json()["geometry"]["capacity_t"] == 300
    assert client.post(f"/api/v1/simulations/{sim}/reset", headers=h).json()["sim_time_s"] == 0
    rep = client.get("/api/v1/reports/SYN-S1", params={"simulation_id": sim, "format": "csv"})
    assert rep.status_code == 200 and rep.text.startswith("# SYNTHETIC")


def test_invalid_inputs(client):
    h = token(client, "engineer")
    req = client.get("/api/v1/config/scenarios/S1_RH_BASELINE_O2_OFF").json()
    req["heat"]["steel_mass_t"] = 9999
    assert client.post("/api/v1/simulations", json={"request": req}, headers=h).status_code == 422
    req = client.get("/api/v1/config/scenarios/S1_RH_BASELINE_O2_OFF").json()
    req["heat"]["composition_ppm"]["C"] = -5
    assert client.post("/api/v1/simulations", json={"request": req}, headers=h).status_code == 422
    req = client.get("/api/v1/config/scenarios/S1_RH_BASELINE_O2_OFF").json()
    req["plant"]["kinetics"]["circulation_multiplier"] = 1.2
    assert client.post("/api/v1/simulations", json={"request": req}, headers=token(client, "operator")).status_code == 422
    assert client.get("/api/v1/simulations/does-not-exist").status_code == 404


def test_compare_job_is_async(client):
    h = token(client, "operator")
    r = client.post("/api/v1/scenarios/compare", json={"scenarios": ["S1_RH_BASELINE_O2_OFF", "S4_HIGH_HYDROGEN"]}, headers=h)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    for _ in range(240):
        j = client.get(f"/api/v1/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert j["status"] == "done", j
    assert len(j["result"]["comparison"]) == 2


def test_closed_loop_mode_feature_gated(client):
    h = token(client, "engineer")
    req = client.get("/api/v1/config/scenarios/S1_RH_BASELINE_O2_OFF").json()
    req["mode"] = "APPROVED_CLOSED_LOOP_EDGE_ONLY"
    assert client.post("/api/v1/simulations", json={"request": req}, headers=h).status_code == 422
