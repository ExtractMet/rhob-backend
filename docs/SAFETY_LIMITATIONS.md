# Safety boundary and limitations

* The Render deployment is an **engineering demonstration / remote advisory environment**. It is NOT a
  safety-rated controller. Render uptime, a browser session or an unvalidated optimizer is never a safety function.
* No API endpoint commands plant equipment. Data adapters are read-only by construction (no write methods).
* `APPROVED_CLOSED_LOOP_EDGE_ONLY` is feature-gated OFF; enabling it requires a separate certified on-premises
  project (OT_INTEGRATION.md), operator approval, DCS/PLC ownership of interlocks and site validation.
* Interlocks in the demo are SIMULATED read-only indicators. The plant DCS/PLC owns all interlocks. No trip
  settings or bypass logic are implemented.
* Oxygen is never recommended or started in the twin when oxygen prerequisites are unknown/false, the grade
  forbids blowing, the vessel bath is too shallow, pressure is above the permissive, circulation is absent or the
  per-heat limit would be exceeded (guards with reason codes).
* Advisory is inhibited (`ADVISORY_INHIBITED`) on model-integrity failure, alarm-class stale/invalid data and
  off-domain inputs.
* Inclusion / total-oxygen outputs are predictions; RH-OB vacuum degassing alone does not certify clean steel.
* Current maturity: **Gate A**. Gates B–D (VALIDATION_PLAN.md) are prerequisites for any plant use.
