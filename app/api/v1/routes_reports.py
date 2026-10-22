from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from ...core.config import SYNTHETIC_BANNER
from ...core.errors import NotFound
from ...core.jsonsafe import SafeJSONResponse
from ...core.security import Principal, current_principal
from ...orchestration.simulation_runner import MANAGER
from ...services.audit import record
from ...services.reporting import material_inputs_outputs

router = APIRouter(prefix="/api/v1/reports", tags=["reports"], default_response_class=SafeJSONResponse)


def _session_for_heat(heat_id: str, simulation_id: str | None):
    if simulation_id:
        return MANAGER.get(simulation_id)
    cands = [s for s in MANAGER.sessions.values() if s.req.heat.heat_id == heat_id]
    if not cands:
        from ...data import repositories as repo
        rows = repo.list_simulations(5, 0, heat_id)
        if not rows:
            raise NotFound(f"no simulation for heat {heat_id}")
        return MANAGER.get(rows[0]["simulation_id"])
    return sorted(cands, key=lambda s: s.created)[-1]


@router.get("/{heat_id}", summary="Heat report (json | csv | html)")
def report(heat_id: str, simulation_id: str | None = None, format: str = Query("json", pattern="^(json|csv|html)$"),
           p: Principal = Depends(current_principal)):
    s = _session_for_heat(heat_id, simulation_id)
    summ = s.summary(include_heavy=True)
    record(p, "REPORT_EXPORT", s.sim_id, format=format)
    if format == "json":
        return {"banner": SYNTHETIC_BANNER, "summary": summ, "trajectory": s.twin.records}
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"# {SYNTHETIC_BANNER}"])
        w.writerow([f"# simulation_id={s.sim_id} heat={heat_id} checksum={summ['reproducibility']['result_checksum']}"])
        keys = [k for k, v in s.twin.records[0].items() if not isinstance(v, (dict, list))]
        w.writerow(keys)
        for r in s.twin.records:
            w.writerow([r.get(k) for k in keys])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{heat_id}_{s.sim_id}.csv"'})
    mio = summ["material_io"]
    ep = summ["endpoint_current_trajectory"]
    k = summ["kpis"]
    rows = "".join(f"<tr><td>{c['target']}</td><td>{c['value']:.4g}</td><td>{c['min'] if c['min'] is not None else ''}</td>"
                   f"<td>{c['max'] if c['max'] is not None else ''}</td><td>{c['unit']}</td><td>{'OK' if c['ok'] else 'NOT MET'}</td></tr>"
                   for c in ep.get("checks", []))
    comp = "".join(f"<tr><td>{el}</td><td>{mio['inputs']['steel_composition_ppm'].get(el) or 0:.1f}</td>"
                   f"<td>{mio['outputs']['steel_composition_ppm'].get(el) or 0:.1f}</td></tr>" for el in mio["inputs"]["steel_composition_ppm"])
    adds = "".join(f"<tr><td>{a['material']}</td><td>{a['mass_kg']:.0f}</td><td>{a['t_s']:.0f}</td><td>{a['purpose']}</td></tr>" for a in mio["inputs"]["additions"])
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>RH-OB heat report {heat_id}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#111}}table{{border-collapse:collapse;margin:8px 0 18px}}td,th{{border:1px solid #999;padding:4px 8px;font-size:12px}}
.banner{{background:#7a1f1f;color:#fff;padding:8px;font-weight:bold}}h2{{border-bottom:2px solid #2b5c8a}}</style></head><body>
<div class="banner">{SYNTHETIC_BANNER}</div><h1>RH-OB Heat Report - {heat_id}</h1>
<p>Simulation {s.sim_id} | scenario {summ['scenario_name']} | grade {summ['grade_id']} | status {summ['status']} | maturity gate {summ['maturity_gate']}</p>
<p>Reproducibility: {summ['reproducibility']}</p>
<h2>Grade checks (RH end / caster arrival)</h2><table><tr><th>Target</th><th>Value</th><th>Min</th><th>Max</th><th>Unit</th><th>Status</th></tr>{rows}</table>
<p>Feasible: <b>{ep.get('feasible')}</b>. Reasons: {ep.get('infeasibility_reasons')}</p>
<h2>Steel composition in / out (ppm)</h2><table><tr><th>Element</th><th>Arrival</th><th>Caster arrival</th></tr>{comp}</table>
<h2>Additions</h2><table><tr><th>Material</th><th>kg</th><th>t (s)</th><th>Purpose</th></tr>{adds}</table>
<h2>KPIs</h2><pre>{k}</pre>
<h2>Closure</h2><p>max relative element residual {summ['mass_balance_relative_error']:.2e}; max relative energy residual {summ['energy_balance_relative_error']:.2e}</p>
<p><i>Inclusion / total-oxygen values are model PREDICTIONS with high uncertainty; RH-OB vacuum degassing alone does not certify clean steel.</i></p>
</body></html>"""
    return HTMLResponse(html)
