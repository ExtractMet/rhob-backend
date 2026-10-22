import math

import pytest

from app.core import units as u


def test_gauge_absolute_roundtrip():
    assert u.gauge_to_absolute_pa(-101000.0) == pytest.approx(325.0)
    assert u.absolute_to_gauge_pa(101325.0) == 0.0
    with pytest.raises(ValueError):
        u.gauge_to_absolute_pa(-200000.0)


def test_normal_vs_actual_gas_flow():
    n = u.nm3h_to_mol_s(3600 * u.MOLAR_VOLUME_NORMAL_M3)  # 1 mol/s
    assert n == pytest.approx(1.0)
    # 1 mol/s at 1873 K and 100 Pa is ~155.7 m3/s actual: normal volume is NOT actual volume
    assert u.actual_m3_per_s(1.0, 1873.0, 100.0) == pytest.approx(8.314462618 * 1873 / 100, rel=1e-9)
    assert u.actual_m3_per_s(1.0, 273.15, 101325.0) == pytest.approx(u.MOLAR_VOLUME_NORMAL_M3, rel=1e-9)


def test_nl_min_nm3h():
    assert u.nl_min_to_nm3h(1000.0) == pytest.approx(60.0)
    assert u.nl_min_to_mol_s(u.mol_s_to_nl_min(2.5)) == pytest.approx(2.5)


def test_temperature_pressure_conversions():
    assert u.c_to_k(1600.0) == pytest.approx(1873.15)
    assert u.pa_to_mbar(133.0) == pytest.approx(1.33)
    assert u.torr_to_pa(1.0) == pytest.approx(133.322, rel=1e-5)
    assert u.mass_fraction_to_ppm(2e-5) == pytest.approx(20.0)
    assert u.kg_s_to_t_min(1000 / 60) == pytest.approx(1.0)
