# OT integration (on-premises / approved private cloud) — template

Architecture: PLC/DCS → historian → **data diode or DMZ / OT-approved edge gateway** → rhob-backend (on-prem
VM/Kubernetes) → operator desk (rhob-frontend) on the L2/L3 network. No inbound path to Level 0–1.

* Protocols: OPC UA (read-only subscriptions, certificate auth, sign & encrypt), historian (PI-like) exports, LIMS REST, MQTT (subscribe only).
* Configuration via environment (`RHOB_OPCUA_ENDPOINT` …); certificates mounted as secrets; no IPs/passwords in code.
* Tag dictionary: `config/sensor_tags_template.csv` (tag, unit, reference state, period, limits, quality policy, calibration date, override role).
* Time sync (NTP/PTP), heartbeat and stale detection (H13), deadbands, unit verification, sample-period matching to avoid PLC load.
* Lab samples persisted separately from continuous tags (sample time vs analysis time).
* Deployment: Docker Compose (provided) or Kubernetes; PostgreSQL (vendor-supported), backups, central logging,
  certificate management, asset inventory, patching, test environment, rollback, DR.
* Prerequisites: site threat/risk assessment, firewall approval, plant safety analysis, MoC. IEC 62443 / ISA-95
  principles applied — **no compliance is claimed without a completed assessment**.
* Closed-loop: only via a separately engineered, certified edge integration with PLC ownership of all limits.
