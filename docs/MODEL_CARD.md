# Model card — RH-OB hybrid twin 1.0.0-demo

* **Intended use**: engineering demonstration, training, what-if studies, advisory prototyping for RH and submerged-tuyere RH-OB.
* **Not intended**: closed-loop control, quality certification, safety functions.
* **Grades (illustrative cards)**: IF-ULC, ULC-DRAWING, LC-DRAWING, ELEC-NO (simplified), LOW-H-PLATE (no O₂), LOW-N-ULC.
* **Operating envelope**: 60–420 t, 1790–1990 K, 30 Pa–1 atm, Ar 0–3200 NL/min (preset-dependent), O₂ ≤ 3000 Nm³/h.
* **Data provenance**: synthetic only (scripts/generate_synthetic_heats.py, seed 42, 90 heats).
* **Uncertainty**: analytic bands (circulation σ 20 %), ensembles on request, EKF covariance; ML quantile PIs.
* **Performance**: no plant accuracy claimed. Synthetic holdout: T residual MAE 5.7 → 1.6 K with hybrid (gate passed); C residual not learnable (gate failed; physics-only kept).
* **Approval history**: none (status `shadow`). Production use requires Gate C/D approvals.
