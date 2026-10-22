import math

import numpy as np
import pytest

from app.core.units import R_GAS
from app.physics import thermodynamics as td


def test_co_equilibrium_constant_1873():
    assert td.log10K("C_O_CO", 1873.0) == pytest.approx(1160 / 1873 + 2.003)
    m = td.co_equilibrium_product(1873.0, 101325.0, 1.0, 1.0)
    assert 0.0022 < m < 0.0026  # classical [C][O] ~ 0.0024 at 1 atm


def test_K_temperature_direction():
    # exothermic deoxidation: K decreases with T ; endothermic H, N dissolution: solubility rises with T
    assert td.K("Al_deox", 1900) < td.K("Al_deox", 1850)
    assert td.h_sieverts_pct(1900, 101325, 1) > td.h_sieverts_pct(1850, 101325, 1)
    assert td.DH["C_O_CO"] < 0 and td.DH["H2_H"] > 0 and td.DH["N2_N"] > 0


def test_van_t_hoff_consistency():
    for name in td.REACTIONS:
        T = 1873.0
        dlnK = (math.log(td.K(name, T + 0.5)) - math.log(td.K(name, T - 0.5))) / 1.0
        dH = dlnK * R_GAS * T * T
        assert dH == pytest.approx(td.DH[name], rel=1e-4)


def test_al_deoxidation_oxygen():
    O = td.o_eq_al(1873.0, 0.04, 1.0, 1.0) * 1e4
    assert 2.0 < O < 6.0  # few ppm at 0.04 % Al


def test_sieverts_values():
    assert td.h_sieverts_pct(1873.15, 101325, 1.0) * 1e4 == pytest.approx(24.6, rel=0.05)
    assert td.n_sieverts_pct(1873.15, 101325, 1.0) * 1e4 == pytest.approx(450, rel=0.05)
    # square-root law
    assert td.h_sieverts_pct(1873, 101325 / 4, 1) == pytest.approx(0.5 * td.h_sieverts_pct(1873, 101325, 1))


def test_activity_coefficients_wagner():
    from app.physics.properties import SPECIES_INDEX, SPECIES
    w = np.zeros(len(SPECIES)); w[SPECIES_INDEX["Al"]] = 0.05; w[SPECIES_INDEX["O"]] = 0.0005
    f = td.activity_coefficients(w)
    assert f[SPECIES_INDEX["O"]] < 1.0  # Al lowers O activity coefficient (e_O^Al < 0)
