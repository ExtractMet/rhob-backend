# Known limitations (honest open issues)

1. All kinetic/transport parameters are illustrative — no plant calibration has been performed.
2. The synthetic "plant" shares the model structure; EKF/ML results demonstrate software behaviour only.
3. ML residual for carbon fails its validation gate on the synthetic set (not learnable from available features) and is not applied; the temperature residual passes (synthetic).
4. Inclusion model is reduced-order (Al₂O₃ only); exogenous inclusions, re-entrainment and clogging are unavailable.
5. Desulfurization, refractory chemistry and skull dissolution are not modelled.
6. The optimizer uses a coarse grid + COBYLA (derivative-free) on 2–3 decisions; it is advisory and takes ~1–3 min per request on 1 CPU.
7. Runtime ~5–7 s per heat on 1 CPU; Render free instances (0.1 CPU, sleep on idle, ephemeral disk) are unsuitable beyond smoke tests.
8. Session restore after restart re-integrates the stored request but does not replay manual lab assimilations.
9. Some literature sources in the brief could not be re-fetched in this session (SOURCES.md, status N).
10. Render plan/region names and Python version strings in render.yaml must be re-verified against current Render documentation at deployment time.
