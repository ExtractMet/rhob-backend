# Model assumptions (explicit, reviewable)

1. Ladle steel = well-mixed active zone + optional slow-mixing sub-zone; vessel + snorkels = one well-mixed zone.
2. Steel hold-up follows the barometric equilibrium with a 5 s lag; ladle level drop is resolved.
3. Circulation from Kuwabara (1988) or a gas-lift energy balance; both require calibration (c_Q, η, ζ) by tracer tests.
4. Decarburization at four sites with mixed C/O transport control; no reverse carburization from CO.
5. Oxygen-jet interface is FeO-saturated; solutes oxidise in affinity order up to their transport supply (reduced-order).
6. H removal liquid-mass-transfer controlled; N removal second order with O/S poisoning (Ban-ya/Fruehan form).
7. Gas phase ideal; one freeboard temperature; duct/cooler at fixed temperature; pump curve as air-equivalent mass capacity with HEI MW correction.
8. Walls: 1-D radial conduction, constant properties per layer, convective + radiative boundaries.
9. Solute mass leaving the steel does not carry steel specific enthalpy; product gases carry their sensible heat (documented enthalpy convention; closure exact).
10. Additions enter cold and dissolve first-order; heating/melting absorbed at dissolution; yield loss booked at charge.
11. Deoxidation products: Al₂O₃ to inclusions; SiO₂/MnO/TiO₂ directly to slag.
12. Inclusions: Al₂O₃ only, 4 size classes; no re-entrainment, no exogenous inclusions, no modification chemistry.
13. Desulfurization, P removal and refractory chemistry (MgO–C oxidation, skull dissolution) are not modelled.
14. Liquidus from a common empirical formula (illustrative).
15. Lab assimilation: scalar Kalman gain per species with exponential carry-forward; booked as explicit correction.
16. Synthetic "plant": the same physics with perturbed kinetics, arrival-assay error and measurement noise — it demonstrates the software, not plant accuracy.
