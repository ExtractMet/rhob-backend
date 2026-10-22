import math

import pytest

from app.physics.circulation import circulation_rate, kuwabara_t_min, energy_balance_kg_s
from app.physics.decarburization import bubble_site, mixed_control_interface
from app.physics.degassing_hn import nitrogen_surface_rate, hydrogen_surface_rate
from app.physics.mixing import mixing_time_95
from app.physics.oxygen_blow import absorption_efficiency, jet_partition
from app.schemas.configuration import KineticsConfig


def test_mixed_control_zero_at_equilibrium_and_nonnegative():
    m = 0.03 * 0.04
    assert mixed_control_interface(0.03, 0.04, m, 500, 300) == 0.0
    assert mixed_control_interface(0.02, 0.03, m, 500, 300) == 0.0  # below equilibrium: no reverse reaction
    assert mixed_control_interface(0.03, 0.04, 1e-7, 500, 300) > 0


def test_rate_limiting_step_switch():
    # ULC with excess O: C transport controls -> rate ~ kC*C
    r1 = mixed_control_interface(0.002, 0.04, 1e-8, 500, 300)
    assert r1 == pytest.approx(500 * 0.002 / 100, rel=0.02)
    # high C, low O: O transport controls -> rate ~ (12/16) kO O
    r2 = mixed_control_interface(0.06, 0.004, 1e-8, 500, 300)
    assert r2 == pytest.approx(300 * 0.004 / 100 * 12.011 / 15.999, rel=0.05)


def test_kuwabara_reference_and_monotonic():
    q = kuwabara_t_min(2500, 0.75, 118000, 100)
    assert 150 < q < 260
    assert kuwabara_t_min(3000, 0.75, 118000, 100) > q
    assert kuwabara_t_min(2500, 0.75, 118000, 1000) < q
    assert kuwabara_t_min(2500, 0.75, 100000, 101325) == 0.0


def test_energy_balance_scaling_matches_kuwabara_exponent():
    a = energy_balance_kg_s(1000, 0.75, 118000, 100, 7000, 1873, 0.04, 4)
    b = energy_balance_kg_s(8000, 0.75, 118000, 100, 7000, 1873, 0.04, 4)
    assert b / a == pytest.approx(2.0, rel=1e-6)  # G^(1/3)


def test_circulation_requires_vessel_pool_and_fouling():
    k = KineticsConfig()
    assert circulation_rate(k, 2500, 0.75, 118000, 100, 7000, 1873, 0.0)["q_kg_s"] == 0.0
    k2 = KineticsConfig(lift_nozzle_fouling=0.0)
    assert circulation_rate(k2, 2500, 0.75, 118000, 100, 7000, 1873, 0.3)["q_kg_s"] == 0.0


def test_bubble_site_caps():
    out = bubble_site(2.0, 10000.0, {"CO": 1e6, "H2": 0, "N2": 0}, 0.5, 3000.0, 0.0005)
    assert out["capped"] and out["CO"] <= 3000 * 0.0005 / 0.012011 * 0.5 + 1e-9


def test_nitrogen_pickup_and_removal():
    k = KineticsConfig()
    r_rem, _ = nitrogen_surface_rate(0.004, 1873, 50.0, 1.0, 7000, 3.5e-4, 50.0, 1.0)
    r_pick, _ = nitrogen_surface_rate(0.004, 1873, 0.79 * 101325, 1.0, 7000, 3.5e-4, 50.0, 1.0)
    assert r_rem > 0 and r_pick < 0


def test_hydrogen_first_order():
    r = hydrogen_surface_rate(0.0004, 1873, 1.0, 1.0, 7000, 6e-4, 50.0)
    r2 = hydrogen_surface_rate(0.0002, 1873, 1.0, 1.0, 7000, 6e-4, 50.0)
    assert r == pytest.approx(2 * r2, rel=0.05)


def test_oxygen_partition_conserves_O():
    n_O = 50.0
    res = jet_partition(n_O, {"Al": 0.0, "Ti": 0.0, "Si": 0.01, "C": 0.04, "Mn": 0.15}, 7000, 0.1)
    used = res["Al"] * 1.5 + res["Ti"] * 2 + res["Si"] * 2 + res["C"] + res["Mn"] + res["FeO"]
    assert used == pytest.approx(n_O)
    assert 0 < absorption_efficiency(8.0, 0.2) < 1 and absorption_efficiency(8, 0) == 0


def test_mixing_time_scales_with_circulation():
    t1 = mixing_time_95(250000, 45000, 25000, 3000, 900)
    t2 = mixing_time_95(250000, 45000, 25000, 1500, 450)
    assert t2 > t1 > 0
