"""Extended Kalman Filter soft sensor for bath carbon, dissolved oxygen and temperature.

Reduced-order model (properly observed; docs/MODEL_EQUATIONS.md section 9):
    x = [C (ppm), O (ppm), T (K), theta (-)]
    dC/dt     = -theta * r_tw(t) * (C - C_eq)/(C_tw(t) - C_eq)            (decarburization)
                r_tw = total twin decarburization rate (all sites: surface, CO nucleation,
                Ar bubbles, O2 jet) -> valid in C- AND O-limited regimes; K = r_tw/(C_tw - C_eq)
    dO/dt     = (M_O/M_C) * dC/dt + s_O(t)                                (O balance; s_O = O supply
                                                                            from OB / leak / deox from twin)
    dT/dt     = r_T(t)                                                    (twin's nominal thermal rate)
    dtheta/dt = 0 + w_theta                                               (unknown kinetic multiplier)
The structural inputs K_app, C_eq, s_O, r_T come from the physics twin trajectory, so the
estimator is a reduced-order projection of the first-principles model, not a black box.

Measurements:
  y1 = off-gas carbon removal rate [ppm/min] = theta K_app (C - C_eq)*60   (continuous; CO+CO2
       analyzer x exhaust flow, delayed and noisy) -> gives theta (unknown-input estimation)
  y2 = dip thermocouple T [K] (at samples)
  y4 = off-gas CARBON BALANCE: C0 - integral(y1 dt) [ppm] (separates C from theta, whose product
       is all that y1 observes -> identifiability); R grows with the integrated removal (5 %).
  Off-gas samples are not used while P > 20 kPa (gas-transport lag of the evacuated volume
  dominates during pump-down).
  y3 = lab C [ppm] (DELAYED: when the result arrives the filter is re-run from the sample
       time using stored inputs/measurements; raw data are never modified)
Process noise Q, measurement noise R are typed in ObserverConfig.
Observability: theta is observable only while K_app (C - C_eq) > 0 (decarburization active).
When it is not (after deoxidation) the filter freezes theta (its variance stays bounded).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ObserverConfig:
    q_C: float = 2.0          # ppm^2 / s  process noise on C
    q_O: float = 4.0          # ppm^2 / s
    q_T: float = 0.004        # K^2 / s
    q_theta: float = 2e-5     # 1/s
    r_offgas_rel: float = 0.10  # relative 1-sigma of off-gas decarburization rate (analyzer + flow + lag)
    r_offgas_abs: float = 0.3   # ppm/min floor
    r_T: float = 3.0 ** 2     # K^2 thermocouple
    r_C_lab: float = 3.0 ** 2  # ppm^2 (C analysis, low-C range)
    P0: tuple = (30.0 ** 2, 60.0 ** 2, 5.0 ** 2, 0.25 ** 2)
    theta0: float = 1.0


@dataclass
class EKF:
    cfg: ObserverConfig
    x: np.ndarray = field(default_factory=lambda: np.zeros(4))
    P: np.ndarray = field(default_factory=lambda: np.eye(4))
    t: float = 0.0

    @classmethod
    def init(cls, cfg: ObserverConfig, C0: float, O0: float, T0: float, t0: float = 0.0):
        e = cls(cfg)
        e.x = np.array([C0, O0, T0, cfg.theta0], dtype=float)
        e.P = np.diag(cfg.P0).astype(float)
        e.t = t0
        return e

    def predict(self, dt: float, u: dict):
        K, Ceq, sO, rT = u["K_app_s"], u["C_eq_ppm"], u["s_O_ppm_s"], u["r_T_K_s"]
        C, O, T, th = self.x
        drive = max(C - Ceq, 0.0)
        dC = -th * K * drive
        f = np.array([dC, (15.999 / 12.011) * dC + sO, rT, 0.0])
        # Jacobian of continuous dynamics
        A = np.zeros((4, 4))
        on = 1.0 if C > Ceq else 0.0
        A[0, 0] = -th * K * on
        A[0, 3] = -K * drive
        A[1, 0] = (15.999 / 12.011) * A[0, 0]
        A[1, 3] = (15.999 / 12.011) * A[0, 3]
        F = np.eye(4) + A * dt
        self.x = self.x + f * dt
        self.x[0] = max(self.x[0], 0.0)  # carbon cannot be negative (logged by caller if active)
        self.x[1] = max(self.x[1], 0.0)
        qC = self.cfg.q_C if K > 0 else 0.005  # no decarburization driving force -> C nearly constant
        Q = np.diag([qC, self.cfg.q_O, self.cfg.q_T, self.cfg.q_theta]) * dt
        self.P = F @ self.P @ F.T + Q
        self.t += dt

    def _update(self, H: np.ndarray, z: float, h: float, R: float) -> dict:
        S = float(H @ self.P @ H.T + R)
        Kg = (self.P @ H.T) / S
        innov = z - h
        # outlier gate (chi2 with 1 dof, 99.9 %)
        nis = innov * innov / S
        if nis > 10.83:
            return {"accepted": False, "innovation": innov, "nis": nis}
        self.x = self.x + Kg * innov
        self.x[3] = min(max(self.x[3], 0.05), 5.0)
        self.P = (np.eye(4) - np.outer(Kg, H)) @ self.P
        return {"accepted": True, "innovation": innov, "nis": nis}

    def update_offgas(self, y_ppm_min: float, u: dict) -> dict:
        K, Ceq = u["K_app_s"], u["C_eq_ppm"]
        C, O, T, th = self.x
        drive = max(C - Ceq, 0.0)
        h = th * K * drive * 60.0
        H = np.array([th * K * 60.0 * (1.0 if C > Ceq else 0.0), 0.0, 0.0, K * drive * 60.0])
        if np.allclose(H, 0.0):
            return {"accepted": False, "innovation": 0.0, "nis": 0.0, "reason": "unobservable"}
        R = (self.cfg.r_offgas_rel * max(abs(y_ppm_min), 1e-3)) ** 2 + self.cfg.r_offgas_abs ** 2
        return self._update(H, y_ppm_min, h, R)

    def update_T(self, T_meas: float) -> dict:
        return self._update(np.array([0.0, 0.0, 1.0, 0.0]), T_meas, self.x[2], self.cfg.r_T)

    def update_C(self, C_meas: float, R: float | None = None) -> dict:
        return self._update(np.array([1.0, 0.0, 0.0, 0.0]), C_meas, self.x[0], self.cfg.r_C_lab if R is None else R)

    def snapshot(self) -> dict:
        sd = np.sqrt(np.maximum(np.diag(self.P), 0.0))
        return {"t_s": self.t, "C_ppm": self.x[0], "O_ppm": self.x[1], "T_K": self.x[2], "theta": self.x[3],
                "C_sd": sd[0], "O_sd": sd[1], "T_sd": sd[2], "theta_sd": sd[3]}


def inputs_from_record(rec: dict, rec_next: dict | None, M_total: float) -> dict:
    """Structural inputs for the reduced model taken from the physics twin record:
    an effective first-order constant K = r_twin / (C_twin - C_eq) built from the twin's total
    site-resolved decarburization rate."""
    Ceq = min(rec.get("C_eq_surface_ppm") or 0.0, 0.5 * (rec.get("C_bulk_ppm") or 0.0))
    n_c = sum((rec.get(k) or 0.0) for k in ("r_C_surface_mol_s", "r_C_inner_mol_s", "r_C_bubble_mol_s", "r_C_jet_mol_s"))
    r_ppm_s = n_c * 0.012011 / max(rec.get("M_total_kg") or M_total, 1.0) * 1e6
    K = r_ppm_s / max((rec.get("C_bulk_ppm") or 0.0) - Ceq, 1e-3)
    if rec_next is not None:
        dt = max(rec_next["t_s"] - rec["t_s"], 1e-6)
        rT = ((rec_next.get("T_bulk_K") or 0) - (rec.get("T_bulk_K") or 0)) / dt
        dO_tot = ((rec_next.get("O_bulk_ppm") or 0) - (rec.get("O_bulk_ppm") or 0)) / dt
        dC_tot = ((rec_next.get("C_bulk_ppm") or 0) - (rec.get("C_bulk_ppm") or 0)) / dt
        sO = dO_tot - (15.999 / 12.011) * dC_tot  # O supply/sink not explained by decarburization
    else:
        rT, sO = 0.0, 0.0
    return {"K_app_s": K, "C_eq_ppm": Ceq, "s_O_ppm_s": sO, "r_T_K_s": rT}


def run_filter(twin_records: list, measurements: dict, cfg: ObserverConfig | None = None,
               C0: float | None = None, O0: float | None = None, T0: float | None = None) -> dict:
    """Run the EKF over the twin's time grid with synthetic/plant measurements.

    measurements = {"offgas": [(t, ppm/min)], "T": [(t, K)], "C_lab": [(t_sample, t_available, ppm)]}
    Delayed lab C is assimilated at its SAMPLE time when it becomes available (filter re-run
    from the sample time); the log records the forecast bias before/after.
    """
    cfg = cfg or ObserverConfig()
    recs = [r for r in twin_records if r.get("T_bulk_K")]
    if len(recs) < 2:
        return {"trace": [], "log": []}
    M = recs[0].get("M_total_kg") or 3e5
    C0 = recs[0]["C_bulk_ppm"] if C0 is None else C0
    O0 = recs[0]["O_bulk_ppm"] if O0 is None else O0
    T0 = recs[0]["T_bulk_K"] if T0 is None else T0
    og = sorted(measurements.get("offgas", []))
    Tm = sorted(measurements.get("T", []))
    labs = sorted(measurements.get("C_lab", []), key=lambda r: r[1])

    def one_pass(lab_set):
        ekf = EKF.init(cfg, C0, O0, T0, recs[0]["t_s"])
        trace = [ekf.snapshot()]
        io = it = 0
        cum = 0.0
        last_og = None
        C_ref = C0
        ilab = sorted(lab_set)
        il = 0
        for k in range(len(recs) - 1):
            r, rn = recs[k], recs[k + 1]
            u = inputs_from_record(r, rn, M)
            ekf.predict(rn["t_s"] - r["t_s"], u)
            while io < len(og) and og[io][0] <= rn["t_s"]:
                t_m, y_m = og[io]
                if last_og is not None:
                    cum += 0.5 * (y_m + last_og[1]) * (t_m - last_og[0]) / 60.0
                last_og = (t_m, y_m)
                if t_m > r["t_s"] and (rn.get("P_Pa") or 1e5) < 20000:
                    ekf.update_offgas(y_m, inputs_from_record(rn, None, M))
                    ekf.update_C(max(C_ref - cum, 0.0), (0.05 * cum) ** 2 + cfg.r_C_lab + 25.0)
                io += 1
            while it < len(Tm) and Tm[it][0] <= rn["t_s"]:
                if Tm[it][0] > r["t_s"]:
                    ekf.update_T(Tm[it][1])
                it += 1
            while il < len(ilab) and ilab[il][0] <= rn["t_s"]:
                if ilab[il][0] > r["t_s"]:
                    ekf.update_C(ilab[il][1])
                    # re-anchor the carbon balance at the lab value
                    C_ref, cum = ilab[il][1], 0.0
                il += 1
            trace.append(ekf.snapshot())
        return trace

    # causal processing: at each lab arrival, re-run with the labs available by then
    log = []
    available = []
    trace_final = one_pass([])
    trace_by_arrival = {}
    for (ts, ta, val) in labs:
        before = one_pass(available)
        available.append((ts, val))
        after = one_pass(available)
        # forecast bias at sample time (pre/post assimilation)
        def at(trace, t):
            best = min(trace, key=lambda s: abs(s["t_s"] - t))
            return best
        pre, post = at(before, ts), at(after, ts)
        log.append({"t_sample_s": ts, "t_available_s": ta, "lab_C_ppm": val, "pre_C_ppm": pre["C_ppm"],
                    "post_C_ppm": post["C_ppm"], "pre_bias_ppm": pre["C_ppm"] - val, "post_bias_ppm": post["C_ppm"] - val,
                    "theta_post": post["theta"]})
        trace_by_arrival[ta] = after
    # assemble a CAUSAL trace: before each arrival time use the trace computed with labs known then
    if labs:
        out = []
        arrivals = sorted(trace_by_arrival)
        for s in trace_final:
            use = trace_final
            for ta in arrivals:
                if s["t_s"] >= ta:
                    use = trace_by_arrival[ta]
            out.append(min(use, key=lambda q: abs(q["t_s"] - s["t_s"])))
        trace_final = out
    return {"trace": trace_final, "log": log, "config": cfg.__dict__}
