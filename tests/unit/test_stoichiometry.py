from app.physics.stoichiometry import REACTION_SET, check_reaction_balance, oxide_element_mass
from app.physics.properties import MW


def test_all_reactions_balanced():
    for name, (r, p) in REACTION_SET.items():
        res = check_reaction_balance(r, p)
        assert all(abs(v) < 1e-12 for v in res.values()), (name, res)


def test_oxide_element_mass():
    d = oxide_element_mass("Al2O3", MW["Al2O3"])
    assert abs(d["Al"] - 2 * MW["Al"]) < 1e-12 and abs(d["O"] - 3 * MW["O"]) < 1e-12
