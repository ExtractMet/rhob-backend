"""Input validation beyond schema bounds: physical plausibility & model validity domain."""
from __future__ import annotations

from ..physics.geometry import derive


def validity_domain_issues(req) -> list[dict]:
    issues = []
    h = req.heat
    c = h.composition_ppm
    if not (1790 <= h.T_arrival_K <= 1990):
        issues.append({"severity": "error", "field": "heat.T_arrival_K", "message": "outside liquid-steel enthalpy model domain 1790-1990 K"})
    if c.get("C", 0) > 2500:
        issues.append({"severity": "warning", "field": "heat.composition_ppm.C", "message": "C > 0.25 %: RH decarburization model calibrated for <= 0.08 %"})
    if c.get("O", 0) > 1200:
        issues.append({"severity": "warning", "field": "heat.composition_ppm.O", "message": "O > 1200 ppm approaches FeO saturation"})
    if c.get("Al", 0) > 0 and c.get("O", 0) > 50:
        issues.append({"severity": "warning", "field": "heat", "message": "Al-killed heat with high dissolved O is thermodynamically inconsistent - check assay"})
    g = req.plant.geometry
    dg = derive(g.model_dump(), h.steel_mass_t * 1000)
    if dg.bath_depth_ladle + g.ladle_freeboard_m > 6.0:
        issues.append({"severity": "warning", "field": "geometry", "message": "ladle bath depth unusually large for diameter"})
    if abs(h.steel_mass_t - g.capacity_t) / g.capacity_t > 0.2:
        issues.append({"severity": "warning", "field": "heat.steel_mass_t", "message": "steel mass differs > 20 % from ladle capacity preset"})
    if g.snorkel_length_m - g.immersion_depth_m >= 1.40:
        issues.append({"severity": "error", "field": "geometry", "message": "vessel bottom too high: barometric column cannot form a vessel bath"})
    if g.immersion_depth_m >= g.snorkel_length_m:
        issues.append({"severity": "error", "field": "geometry", "message": "immersion depth >= snorkel length"})
    return issues
