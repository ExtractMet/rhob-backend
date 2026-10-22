from hypothesis import given, settings, strategies as st

from app.core import units as u
from app.physics.decarburization import mixed_control_interface


@given(C=st.floats(1e-5, 0.1), O=st.floats(1e-5, 0.1), m=st.floats(1e-9, 1e-2), kC=st.floats(1, 2000), kO=st.floats(1, 2000))
@settings(max_examples=400, deadline=None)
def test_decarb_flux_bounded_nonnegative(C, O, m, kC, kO):
    r = mixed_control_interface(C, O, m, kC, kO)
    assert r >= 0.0
    assert r <= kC * C / 100.0 + 1e-15  # never removes more than the transport capacity for all C


@given(q=st.floats(0, 1e5))
def test_gas_unit_roundtrip(q):
    assert abs(u.nm3h_to_nl_min(u.nl_min_to_nm3h(q)) - q) <= 1e-9 * max(q, 1)
