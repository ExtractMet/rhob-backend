# Validation plan and plant acceptance gates

## Maturity gates
| Gate | Content | Status |
|---|---|---|
| A — Software complete | clean install of both repos, local/Docker run, synthetic end-to-end heat, 3D animation, API, automated tests, documents | **achieved (this release)** |
| B — Physical consistency | element/energy closure, thermodynamic checks, identifiable parameters, uncertainty plots, stable dynamics, all stages | largely demonstrated on synthetic data; independent review required |
| C — Historical plant validation | NDA, tag dictionary, benchmark heats (O₂ on/off, vacuum perturbations, grades, sensor faults), heat-level holdout, calibration, out-of-domain detection, KPIs vs site-set thresholds | NOT STARTED — needs plant data |
| D — OT controlled integration | cybersecurity review, shadow pilot, FAT/SAT, failover, operator acceptance, HAZOP/risk, MoC, DCS/PLC ownership, authority approval | NOT STARTED |

## Calibration sequence (Gate C)
1. Geometry & pump curve from drawings and ejector test.  2. Circulation c_Q from tracer (Cu/Ni) mixing tests.
3. Thermal: refractory properties, h_in, emissivities from temperature-drop heats (O₂ off).
4. Decarburization k_C, splash factor, bubble ε, a_in from C trajectories (O₂ off); jet kA, λ from O₂-on heats.
5. H, N kinetics (k_H, k_N, k_r0, K_O, K_S) from degassing heats with Hydris/N samples.
6. Inclusion model only if T.O./inclusion data exist; otherwise remains UNAVAILABLE.
Identifiability: parameters are calibrated sequentially on data sets that excite them; profile likelihood /
Fisher information is checked so that several parameters are not fitted to a single trace.

## Scientific validation matrix
| Output | Data | Metric (thresholds set by plant) |
|---|---|---|
| C trajectory / endpoint | lab C, off-gas | MAE, bias, 90 % PI coverage on withheld heats |
| T trajectory / endpoint | dip T | MAE, drop-rate error |
| H, N endpoint | Hydris, lab N | MAE, infeasibility detection rate |
| Pressure / pump | PT, ejector status | dynamic error during pump-down and CO surges |
| Al / O after deox | lab Al, O-probe | MAE |

## Software FAT/SAT
FAT: CI suites green, load test (concurrent sessions), restart/persistence, role tests, export integrity.
SAT: shadow-mode operation ≥ an agreed number of heats, operator acceptance, failover, cybersecurity scan.
No accuracy number (e.g. "C within 5 ppm") is claimed before demonstration on withheld real heats.
