# RH-OB Operator Desk — Operator & Engineer Manual

Release 1.0.0-demo · Extractmet Private Limited · **Engineering demonstration — not connected to plant controls.**

## 1. Screen layout
* **Red safety strip** (always visible): demonstration status, maturity gate, ADVISORY_INHIBITED flag.
* **Top bar**: plant / station / heat / grade / **mode** / status / simulated time / stage chips; backend connection
  badge; demo **role** selector (Viewer, Operator, Metallurgist, ProcessEngineer, Admin — the backend enforces
  permissions); **display units** (°C·mbar·Nm³/h·ppm, K·Pa·NL/min, °C·kPa·Nm³/h·wt%); light/dark theme.
* **Left navigation**: 16 pages.
* **Control bar** (every page):

| Control | Function | Disabled when |
|---|---|---|
| Simulation selector / ⟳ | choose a persisted simulation (shared by all pages, kept in the URL `?sim=`) | — |
| Scenario + *New heat* | create a heat from a synthetic scenario at t = 0 | busy |
| *Validate inputs* | backend schedule + validity-domain check of the selected scenario | busy |
| *Run heat ▶▶* | integrate to the end of the schedule | completed, paused, busy |
| *+60 s* | advance the simulation clock 60 s | completed, paused |
| speed + *Play ▶* | auto-advance at ×10/×30/×60 simulated s per wall s (server ticker) | completed, paused, already playing |
| *Pause ❚❚* | **freezes the simulation clock** (server refuses steps) | not running |
| *Resume* | un-freeze (manual stepping) | not paused |
| *Reset* | back to t = 0, same request & seed (confirmation) | busy |
| *Apply lab result (n)* | assimilate the latest available lab result (delayed reconciliation) | no result available |
| *Request optimization* | opens page 12 and starts a job | — |
| *Compare scenario* | opens page 11 | — |
| Export (CSV / JSON / HTML report) | audited export with the SYNTHETIC banner | — |

Value labels: MEASURED, LAB ANALYZED, SOFT-SENSED, PREDICTED, ESTIMATED, OPTIMIZED, USER-DEFINED, UNAVAILABLE.
All charts share the time cursor (hover one chart → all show the same time), show stage bands, event markers
(O₂ ON/OFF, additions, samples, vacuum break, pump-down) and a "SYNTHETIC" watermark; use the camera icon to
export PNG; tables have filter, sort and CSV download.

## 2. Pages
**01 Operational Overview** — 16 state tiles (T, P, C, O, H, N, Al, circulation, t95, O₂, Ar, T.O., superheat,
cost/t, mass & energy closure), stage timeline, live station schematic, grade endpoint checks (forecast), key
trends, advisory cards (acknowledge/defer/reject are audited), alarms, events.

**02 3D RH-OB Plant & Schematic** — Three.js cutaway: ladle (steel heat-shaded by temperature, slag), up-/down-leg
snorkels with Ar nozzle ring, lower/upper vacuum vessel with O₂ tuyeres, off-gas duct, cooler, 5-stage ejector
train, alloy hopper, ladle lift. Particles: Ar bubbles (grow under vacuum), steel tracers (speed ∝ circulation),
CO bubbles and splash, O₂ jets, off-gas flow, alloy drops — all bound to the model state at the scrubber time.
Controls: rotate/zoom/pan, auto camera, cutaway, shell opacity, labels, camera presets, playback scrubber with
×10–×120 compression, *Simulated* vs *Actual (synthetic plant truth)* toggle, click equipment to inspect live
values. Keyboard: Space, ←/→, C, L. Without WebGL a 2D schematic is shown. Below: full process schematic with
instrument tags at the scrubber time, equipment dimension table, list of modelled regions.

**03 Heat Setup & Configuration** — load a scenario template; **ladle capacity presets 100–350 t** (geometry,
pump curve, O₂/Ar limits, lift-gas schedule scaled); equipment variant (RH / RH-OB); mode; heat arrival data
(mass, T, 16 elements, slag mass & composition); grade card; plant limits & vacuum (pump health, leak, vent gas,
ejector curve); geometry & dimensions with derived values (bath depth, vessel bottom height, barometric lift,
expected vessel bath); **refractory design** per wall (materials, thicknesses, k/ρ/c_p, steady-flux estimate,
add/remove layers); thermal & kinetic calibration (ProcessEngineer); additions (with O-probe auto-deox target);
schedule editor (stage, duration, pressure ramps, Ar, O₂, pumps, immersion, vent). Out-of-bound inputs are
highlighted and rejected (never silently clamped). *Validate*, *Create & run*, *Create (step mode)*, export/import JSON.

**04 Live Trends & Reconciliation** — C (lab ◆ vs model), O & Al, T (thermocouple ◆), H & N, P vs set-point, gas
flows, circulation & t95, off-gas species, closure residuals, forecast history. *Forecast to end + 90 % bands*
overlays the forecast from the current state; *overlay synthetic plant truth*; lab table with status IN LAB /
AVAILABLE / APPLIED; SSE live packet feed while playing (auto-reconnect with Last-Event-ID, stale-data flag).

**05 Model & Balance Ledger** — cumulative energy ledger (sources/sinks vs stored-energy change), heat-flow rates,
closure residuals, energy totals, **element ledger across all reservoirs** with residual row, thermochemistry at
bath T, state-vector layout & solver statistics, equation summary.

**06 Vacuum, Pumps & Off-gas** — pressure vs set-point and bubble pressure, pump capacity & throttle, off-gas flows
by species, gas composition, ejector curve with operating points, actual volumetric speed, pumped gas & steam.

**07 Oxygen, Argon & Circulation** — O₂ flow / absorption / cumulative, jet oxygen partition (CO, FeO, Al₂O₃, SiO₂,
MnO, TiO₂, slip), FeO pool & post-combustion, circulation (raw vs saturated) vs Ar, hold-up & vessel bath depth,
mixing time & recirculation number, tracer response (t95 with CI), circulation vs argon map.

**08 Decarburization & H/N** — decarburization by site (surface, CO nucleation, bubbles, jet), cumulative C removed,
equilibria, **C–O path vs equilibrium lines**, K_app & reactive area, H and N vs Sieverts equilibria, zone gradient,
composition table (arrival, RH end, ladle, vessel, caster).

**09 Deoxidation, Alloying & Cleanliness** — Al/O/O_eq(Al), inclusion size classes, total O, alloying elements,
slag composition, slag–metal reoxidation, additions table, output availability table (what is predicted vs unavailable).

**10 Thermal & Refractory** — temperatures (zones, slag, gas), stacked heat losses/sinks, hot-face & shell
temperatures, ladle wall field (node × time), wall profiles at a selected time, superheat & liquidus.

**11 What-if & Batch** — choose scenarios (+ current heat) → background comparison job → overlaid C, T, N, P, T.O.
and a KPI/endpoint table; *Ensemble uncertainty* (8 members, 5–50–95 % bands).

**12 Optimizer & Recommendations** — budget & iterations → job (feasibility grid → COBYLA economics →
chemical-heating energy balance → finite-difference sensitivity → verification run). Shows status
(FEASIBLE_PLAN / NO_FEASIBLE_PLAN), limiting constraint, decisions baseline vs optimized, constraint margins,
C and T comparison, cost-time frontier, sensitivity, optimized phases, alternatives, approval & actuator authority.
If the deep-vacuum phase is already over, the whole heat is re-planned from t = 0 (planning mode).

**13 Alarms, Interlocks & Events** — simulated alarm list (acknowledge is audited), event timeline, events log,
state machine with blocked transitions and reason codes, hazard registry (detection, message, manual response,
interlock owner, inhibit rule).

**14 History, Estimation & Validation** — persisted simulations (replay links), **EKF soft sensor** (C ± 2σ vs
synthetic plant truth and lab, T and kinetic multiplier θ), delayed-lab assimilation log (pre/post bias), twin
reconciliations, ML validation report with **validation gates**, permutation importance, parity plot, drift (PSI).

**15 Economics & Material I/O** — cost/t (illustrative prices), consumptions, inputs & outputs tables with weights
and compositions (steel, slag, gases, additions, off-gas), composition and slag in→out charts, element ledger.

**16 Admin & Docs** — user/role, backend metadata & readiness, adapter status, audit log, live sessions, documentation.

## 3. Example workflow (scenario S2, RH-OB oxygen-assisted)
1. 03 → template S2, preset 300 t → *Validate* → *Create (step mode)*.  2. *Play ×30*; watch 02 (O₂ jets during
OB_DECARB) and 04.  3. When the 22-min lab C is AVAILABLE, *Apply lab result* — the forecast changes.  4. 12 →
*Request optimization*.  5. Export the HTML report.

## 4. Interpreting results
Forecasts are model predictions with stated bands. A grade target marked NOT MET with "oxygen-limited" means more
dissolved oxygen is needed (OB), "time/kinetics-limited" means longer deep vacuum or more circulation. Nitrogen
targets can be physically unattainable in the available time (second-order kinetics). Inclusion outputs are low
confidence. Everything shown is SYNTHETIC in this release.
