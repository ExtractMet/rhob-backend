# Sources and bibliographic audit

Status legend: **V** = verified in this build session (fetched/quoted), **K** = standard reference cited from
domain knowledge (bibliographic details believed correct; re-check before publication), **N** = listed in the
client brief but NOT re-fetched in this session (automated fetch required an approval that was unavailable).

## Process / kinetics
| # | Reference | Use | Status |
|---|---|---|---|
| K1 | Kuwabara T., Umezawa K., Mori K., Watanabe H., "Investigation of decarburization behavior in RH-reactor and its operation improvement", Trans. ISIJ 28(4) (1988) 305–314 | circulation correlation Q = 11.4 G^1/3 D^4/3 [ln(P1/Pv)]^1/3 (t/min, NL/min, m, Pa) | **V** (formula and units quoted in J. Iron Steel Res. Int., doi:10.1007/s42243-022-00752-0, Eq. 24) |
| K2 | Ono K. et al., "The circulation rate of RH degassing process by water model experiment", Electric Furnace Steel 52(3) (1981) 149 | background, circulation | **V** (citation seen in doi:10.1007/s12613-012-0584-4) |
| K3 | Nippon Steel Technical Report No. 61 (1994), Recent Advances in Ultralow-Carbon Steel Refining Technology, https://www.nipponsteel.com/en/tech/report/nsc/pdf/6103.pdf | ULC practice context | **N** |
| K4 | Circulation flow and decarburization model, Vacuum (2018), https://doi.org/10.1016/j.vacuum.2018.04.007 | context | **N** (DOI from brief, not resolved) |
| K5 | US Patent US5520718A, https://patents.google.com/patent/US5520718A/en | RH/RH-OB oxygen blowing context | **N** |
| K6 | Tenova RH vacuum degasser; Primetals RH plants (vendor pages in brief) | equipment context only — no vendor data used | **N** |
| K7 | Turkdogan E.T., Fundamentals of Steelmaking, The Institute of Materials, London, 1996 | equilibrium data T2 | **K** |
| K8 | Sigworth G.K., Elliott J.F., "The thermodynamics of liquid dilute iron alloys", Metal Science 8 (1974) 298–310 | solution free energies, Wagner parameters, Sieverts | **K** |
| K9 | JSPS 19th Committee, Steelmaking Data Sourcebook, Gordon & Breach, 1988 | equilibrium/interaction data | **K** |
| K10 | Ban-ya S., Fruehan R.J. and co-workers (N₂ kinetics, surface-active poisoning; e.g. Glaws & Fruehan, Metall. Trans. B 1985) | rate-law FORM only; magnitude calibrated | **K** |
| K11 | Saffman P.G., Turner J.S., J. Fluid Mech. 1 (1956) 16–30 | turbulent collision kernel | **K** |
| K12 | Zuber N., Findlay J.A., J. Heat Transfer 87 (1965) 453 | drift-flux gas hold-up | **K** |
| K13 | Heat Exchange Institute, Standards for Steam Jet Vacuum Systems (molecular-weight entrainment ratio) | pump MW correction | **K** |

## Deployment / security (from the brief)
| Reference | Status |
|---|---|
| Render: Deploy FastAPI https://render.com/docs/deploy-fastapi | **N** — settings follow Render conventions (bind 0.0.0.0:$PORT, default 10000); re-verify at deploy time |
| Render web services https://render.com/docs/web-services | **N** |
| Streamlit Docker deployment (not used — GUI is Python/CSS/Three.js per client instruction) | n/a |
| ISA/IEC 62443 overview https://www.isa.org/standards-and-publications/isa-standards/isa-iec-62443-series-of-standards | **N** — principles applied; no compliance claimed |

## Software dependencies (licences)
FastAPI MIT · Uvicorn BSD-3 · Pydantic MIT · NumPy BSD-3 · SciPy BSD-3 · scikit-learn BSD-3 · pandas BSD-3 ·
SQLAlchemy MIT · Alembic MIT · PyYAML MIT · httpx BSD-3 · psycopg LGPL-3 · three.js MIT · plotly.js MIT · Jinja2 BSD-3.

No proprietary figures, kinetic tables, OEM drawings, photographs or CAD were used; all geometry is procedural.
All kinetic magnitudes are ILLUSTRATIVE and must be calibrated.
