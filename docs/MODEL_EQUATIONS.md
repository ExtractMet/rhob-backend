# RH-OB Digital Twin — Model Equations, Numerical Method and Validity

Version 1.0.0-demo · Extractmet Private Limited · Maturity **Gate A** (software complete; NOT plant-validated)

This document lists every state variable and equation implemented in `app/physics/`. Section numbers
match the `[Eq x.y]` tags in `app/physics/solver.py`. All parameters marked ILLUSTRATIVE are
demonstration defaults to be calibrated on plant data (see `VALIDATION_PLAN.md`).

---

## 1. Units and conventions

| Quantity | Internal unit | Notes |
|---|---|---|
| mass | kg | steel, slag, inclusions, additions |
| composition | mass fraction (kg/kg) | thermodynamics uses wt% (×100); display ppm |
| pressure | Pa **absolute** | gauge never used internally |
| temperature | K | display °C |
| energy / power | J / W | ledger displayed in MJ, MW |
| amount of gas | mol | flows in mol/s |
| gas flow display | Nm³/h, NL/min | **normal = 273.15 K, 101 325 Pa** (amount, not actual volume) |

Actual volumetric flow at vessel conditions: `V̇ = ṅ R T / P` (`core/units.actual_m3_per_s`). A normal
volume flow is never used as an actual volume (the actual Ar volume at 100 Pa and 1873 K is ~1700× the
normal volume).

Enthalpy reference: **solid steel at 298.15 K has h = 0**. Liquid steel:
`h(T) = H₁₈₀₀ + c_p,l(w)(T − 1800)`, `H₁₈₀₀ = 0.75 kJ/kgK·(1809−298.15) + 247 kJ/kg − 824·9 J/kg`,
`c_p,l(w) = 824(1 − Σw_i) + Σ w_i c_p,i` (Mn, Si, Cr, Ni, Al, Mo, Cu, Ti, C partial heats). Valid 1790–2000 K.

## 2. Zones and state vector (`physics/state_vector.py`)

Zones: **l** ladle active (well mixed, circulation loop), **d** ladle slow-mixing sub-zone (optional,
three-zone model, mass fraction φ_d), **v** vacuum-vessel zone (snorkels + vessel bath).

| Block | Size | Unit | Meaning |
|---|---|---|---|
| `M_z` | 1/zone | kg | steel mass |
| `H_z` | 1/zone | J | steel enthalpy |
| `m_z[16]` | 16/zone | kg | dissolved C, O, H, N, Al, Si, Mn, Ti, S, P, Cr, Ni, Nb, V, Cu, Mo (Fe = M − Σm) |
| `inc_z[4]` | 4/zone | kg | Al₂O₃ inclusions, radii 2.5 / 7.5 / 20 / 50 µm |
| `slag[7]`, `H_slag` | 8 | kg, J | FeO, MnO, SiO₂, Al₂O₃, CaO, MgO, TiO₂; slag enthalpy |
| `feo_pool` | 1 | kg | oxygen-jet FeO not yet dissolved |
| `add[k]` | per material | kg | undissolved additions |
| `Tw_ladle`, `Tw_vlow`, `Tw_vup` | ~8 each | K | refractory finite-volume node temperatures |
| `gas[6]` | 6 | mol | Ar, CO, CO₂, O₂, N₂, H₂ in vessel + duct |
| accumulators | ~45 | mol, kg, J | gas in/out, skull, Ar bypass, O₂ via tuyeres, energy ledger (22 terms), circulated mass, C removed per site |

Typical size: 150 states (three-zone, three additions).

## 3. Steel species and enthalpy balances [Eq 6.1]

With circulation `q_c` (kg/s), hold-up change `q_h = dM_v/dt|transport` and slow-zone exchange `q_ex`:

```
dm_i,l/dt = q_c(w_i,v − w_i,l) − q_h w_i,donor + q_ex(w_i,d − w_i,l) + R_i,l
dm_i,v/dt = q_c(w_i,l − w_i,v) + q_h w_i,donor + ṁ_i,add + R_i,v
dm_i,d/dt = q_ex(w_i,l − w_i,d) + R_i,d
dH_z/dt   = Σ ṁ h (same transport terms with h_z = H_z/M_z) + Σ(−ΔH_r) r − Σ ṅ c̄_p (T − 298) − q_walls − q_slag
```
`donor = l` if `q_h ≥ 0` else `v`. Reaction terms `R_i` include each gas-phase stoichiometry exactly once
(decarburization removes C **and** O from steel and adds CO to the gas phase; O₂ from tuyeres is never
counted both as dissolved O and as direct CO).

**Hold-up (barometric) [6.1b]** `h_b = (P_atm − P_v)/(ρg)`; vessel bottom height `h_vb = L_sn − h_imm + Δz`
(ladle level drop Δz iterated); `M_v,eq = ρ[2A_sn(h_imm − Δz + min(h_b,h_vb)) + A_v max(h_b − h_vb, 0)]`;
`dM_v/dt = (M_v,eq − M_v)/τ_h` (τ_h = 5 s). Immersion and withdrawal are discrete, conservative mass/enthalpy
transfers between zones at phase boundaries.

## 4. Circulation and mixing [Eq 6.2] (`physics/circulation.py`, `physics/mixing.py`)

Kuwabara et al., Trans. ISIJ 28 (1988) 305–314:
`Q [t/min] = 11.4 G^{1/3} D^{4/3} [ln(P₁/P_v)]^{1/3}` — G lift gas [NL/min], D up-leg Ø [m], P₁ pressure at
the injection point `P_atm + ρ g d_noz`, P_v vessel pressure.

Alternative physically based gas-lift energy balance:
`η ṅ_g R T ln(P₁/P_v) = ½ ζ ρ u² Q/ρ ⇒ Q = ρA[2ηṅRT ln(P₁/P_v)/(ζρA)]^{1/3}` — reproduces the G^{1/3}
[ln(P₁/P_v)]^{1/3} scaling; η and ζ are calibration parameters.

Corrections: nozzle fouling `G_eff = θG` (bypass gas leaves through the ladle), hydraulic saturation
`Q/(1+(Q/Q_max)⁴)^{1/4}` with `Q_max = ρA u_max`, vessel-pool factor (smoothstep over the first 0.1 m of
vessel bath), calibration factor `c_Q` with stated 1σ (default 20 %, uncalibrated).

Mixing: linear zone network `dc/dt = A c`; `t₉₅ = ln 20/|λ₂|`; tracer response by matrix exponential;
recirculation number `∫q_c dt / M`.

## 5. Thermodynamics [Eq 6.3] (`physics/thermodynamics.py`)

`log₁₀K = A/T + B`, `K = exp(−ΔG°/RT)`, `ΔH = −2.303 R A` (van 't Hoff — reaction heats are consistent with
the equilibrium constants; verified by `tests/unit/test_thermo.py`).

| Reaction | Data | Source |
|---|---|---|
| [C] + [O] = CO(g) | log K = 1160/T + 2.003 | Turkdogan 1996; JSPS 1988 |
| ½O₂ = [O] | ΔG° = −117 110 − 3.39T | Sigworth & Elliott 1974 |
| 2[Al] + 3[O] = Al₂O₃ | ΔG° = −1 202 000 + 386.3T | Turkdogan 1996 |
| [Si] + 2[O] = SiO₂ | log K = 30 410/T − 11.59 | Turkdogan 1996 |
| [Mn] + [O] = MnO | log K = 14 450/T − 6.43 | Turkdogan 1996 |
| [Ti] + 2[O] = TiO₂ | ΔG° = −675 580 + 229.4T (Hess-law derived, lower confidence) | derived |
| Fe + [O] = FeO(l) | log K = 6150/T − 2.604 | Turkdogan 1996 |
| ½H₂ = [H] | log[%H] = −1905/T − 1.591 + ½log p_H₂ | Sigworth & Elliott 1974 |
| ½N₂ = [N] | log[%N] = −188/T − 1.246 + ½log p_N₂ | Sigworth & Elliott 1974 |

Activities: Henrian 1 wt% standard state, first-order Wagner `log f_i = Σ e_i^j [%j]` (Sigworth & Elliott
1974 / JSPS 1988 values; missing pairs = 0; |log f| bounded at 3 with a validity flag).

## 6. Decarburization kinetics [Eq 6.4] (`physics/decarburization.py`)

Mixed control at every site j: `k_C(C − C_i) = (M_C/M_O) k_O (O − O_i)`, `C_i O_i = p_CO,i/(K f_C f_O)`
→ quadratic `r C_i² + (O − rC) C_i − m = 0`, `r = (M_O/M_C) k_C/k_O`. Flux `ρk_C A(C − C_i)/100 ≥ 0`, exactly
zero at/under equilibrium (no reverse carburization). The controlling step switches automatically:
O-transport control at high C/low O (oxygen supply needed), C-transport control in the ULC regime.

* **Free surface + splash/droplets**: `A_s = A_v·min(1 + κ √U_g, κ_max)`, U_g = actual superficial lift-gas
  velocity at vessel P,T; `p_CO = x_CO P_v`.
* **In-bath CO nucleation**: active depth `z* = (p_eq − P_v − ΔP_nuc)/(ρg)`, volumetric capacity `ρ a_in A_v z*`,
  equilibrium at mid-depth pressure — vanishes in the ULC regime.
* **Ar lift bubbles**: `ṅ_i = ε ṅ_Ar p_i,eq/(P_b − Σp_eq)` (CO, H₂, N₂ jointly), Σp_eq ≤ 0.9 P_b, bounded by
  the carbon convected through the up-leg; P_b = log-mean pressure between P₁ and P_v.
* **O₂ jet** (section 7).

Lumped display constant (Kuwabara 1988): `K_app = (Q/W)·ρak/(Q + ρak)`.

## 7. RH-OB oxygen [Eq 6.5] (`physics/oxygen_blow.py`)

`η_abs = 1 − exp(−λ h_sub)` (h_sub = bath depth above tuyere). Absorbed O (mol/s) is allocated at the jet
interface in affinity order Al > Ti > Si > C, each **transport-limited** (`ρ kA_jet [%i]/100/M_i`); Mn competes
with Fe for the residual through `K_MnFe[%Mn]/(1 + K_MnFe[%Mn])`; the remainder forms FeO. FeO enters a pool
that dissolves (`FeO → Fe + [O]`, rate `k(1 − O/O_sat)`) or is lost to skull. Slip O₂ reaches the freeboard:
post-combustion `CO + ½O₂ → CO₂` (fraction, limited by CO), heat fraction to bath. Energetics by Hess's law
through ½O₂ → [O]. Aluminium heating only when Al is scheduled AND `chemical_heating_enabled` (guard).

## 8. Hydrogen and nitrogen [Eq 6.6] (`physics/degassing_hn.py`)

H: liquid-side control `J_H = ρk_H A(H − H_eq)/100`, Sieverts equilibrium at `p_H₂ = x_H₂P_v`.
N: interfacial second-order kinetics in series with mass transfer,
`J_N₂ = k_r(p_N₂,i − p_N₂,gas)`, `k_r = k_r0/(1 + K_O a_O + K_S a_S)²` → quadratic for [N]_i. Reversible:
air leaks / N₂ vent produce pick-up. Bubble-site N uses the poisoning ratio k_r/k_r0. H and N therefore
degas differently; low-N targets are reported infeasible when kinetics cannot reach them.

## 9. Vacuum gas phase [Eq 6.7] (`physics/vacuum_gas.py`)

`dn_i/dt = ṅ_gen,i + ṅ_inj,i + ṅ_leak,i + ṅ_vent,i − x_i (ṅ_exh + ṅ_relief)`;
`P = n R/(V_free/T_g + V_duct/T_duct)`, `V_free = V_vessel − V_steel,vessel`, `T_g = ½(T_v + T_wall,up)`.
Pump: `ṅ_max = W_air(P)/(3600 M_air)·√(M_air/M̄)·health` (HEI molecular-weight entrainment), throttle
`u = ½[1 + tanh((P − P_sp)/(βP_sp + 5 Pa))]`. Air leak is choked (≈ independent of P) and scaled down near
atmosphere; leaked O₂ is partly absorbed by the bath. Vacuum break: vent gas (N₂/Ar/air) until ≈P_atm.

## 10. Energy [Eq 6.8] (`physics/thermal.py`, solver)

Walls: concentric cylindrical finite volumes (layers from the refractory library; 4 nodes in the working
lining), `C_k dT_k/dt = G_{k−1,k}(T_{k−1} − T_k) − G_{k,k+1}(T_k − T_{k+1})`, series cylindrical resistances.
Hot face: steel convection (`h_in`, wetted fraction), freeboard radiation (two-surface enclosure, ε_eff).
Cold face: `h(T_s − T_a) + εσ(T_s⁴ − T_a⁴)` solved for the shell temperature (Newton). Slag: lumped, conduction
through half thickness + film to steel, top radiation with view factor (reduced under ladle cover during dispatch).
Gas sensible heat: every gas leaving/heated by the bath carries `ṅ c̄_p(T − 298)`.

**Ledger** (all integrated as states): sources = O₂→[O], C+O→CO, Al₂O₃, SiO₂, MnO, TiO₂, FeO formation,
FeO dissolution (−), solution heats of additions, H/N degassing, slag reoxidation (−), post-combustion to
bath; sinks = gas sensible, ladle shell, lower vessel shell, upper vessel shell, slag top radiation.
Closure: `E_stored(t) − E_stored(0) = Σsources − Σsinks` with `E_stored = ΣH_z + H_slag + ΣC_k(T_k − 298)`.

## 11. Alloying, deoxidation, slag and cleanliness [Eq 6.9]

Dissolution: `dm/dt = −m/τ`, `τ = max(min(1.6 τ_melt, τ_diff), 2 s)`,
`τ_melt = ρ_a r[c_p(T_m − 298) + L]/(3h(T − T_m))` (shell model), `τ_diff` for high-melting alloys. Yield
loss is booked to a loss reservoir at charge. O-probe deoxidation: Al mass computed at addition time from
the dissolved O and Al target. Deoxidation relaxation `r_O = k_d M (O − O_eq,i)⁺` for Al, Ti, Si, Mn.
Al₂O₃ → inclusion class 0; SiO₂, MnO, TiO₂ → slag. Slag–metal O transfer
`J_O = k_sm A ρ (O_eq(a_FeO) − O)/100`, `a_FeO = γ X_FeO`. Inclusions: Saffman–Turner aggregation
(ε from circulation/expansion work), Stokes flotation, Ar-bubble capture; T.O. = dissolved O + inclusion O.
**These are low-confidence predictions; exogenous inclusions, inclusion chemistry and clogging are UNAVAILABLE.**

## 12. Numerical method

`scipy.integrate.solve_ivp(method="BDF")` (Radau/LSODA selectable), rtol 1e-6 (demo), per-state atol,
`max_step ≤ 10 s`; segments split at phase changes, additions, samples and abort; dense Jacobian by finite
differences. No clipping: negative excursions are logged as events. Wall-time budget per run with
failure status. Typical cost (1 CPU, 2026 reference container): 4–7 s for a 50-min heat (≈150 states,
~15 000 RHS evaluations); BLAS pinned to 1 thread (oversubscription slows LU factorization 100×).

## 13. Closure checks and invariants

Every recorded step: element inventory (Fe, C, O, H, N, Al, Si, Mn, Ti, S, P, Cr, Ni, Nb, V, Cu, Mo, Ca, Mg)
across steel zones, slag, inclusions, FeO pool, undissolved additions, vessel gas, exhausted gas, skull and
yield losses versus initial + gas inputs + additions; argon balance; energy ledger. Tolerances:
mass 1e-6, energy 1e-4 relative (SolverConfig) — a run exceeding them ends with status `failed`
(`BALANCE_VIOLATION`). Lab assimilations are external corrections, booked as explicit ledger lines.

## 14. Reduced-order estimator (EKF) — see `estimation/observer.py`

`x = [C, O, T, θ]`, `dC/dt = −θ r_tw (C − C_eq)/(C_tw − C_eq)` using the twin's total site-resolved rate,
O balance and thermal rate from the twin. Measurements: off-gas decarburization rate, off-gas carbon
balance (separates C from θ), thermocouple, delayed lab C (re-filtered from sample time; pre/post bias
logged), χ² outlier gate.

## 15. Validity domain

Dilute Fe-based melts (Σ solutes < 35 wt%, C ≤ 0.25 %), 1790–1990 K, P_v 30 Pa – 1 atm, 60–420 t ladles,
RH and submerged-tuyere RH-OB hardware. RH-KTB (top lance) is a distinct variant and is rejected.
Outside this domain the API returns validation errors or warnings.
