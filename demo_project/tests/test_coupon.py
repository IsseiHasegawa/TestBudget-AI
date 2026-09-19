import pytest

from app.coupon import Coupon, CouponError, apply_coupon, discount_for, waives_shipping
from support import simulate_io


def test_percent_discount_on_round_subtotal():
    """Ten percent of 1000 needs no rounding decision."""
    simulate_io(5.0)
    coupon = Coupon(code="SAVE10", kind="percent", value=10)
    assert discount_for(coupon, 1000) == 100


def test_percent_discount_truncates_partial_cent():
    """Ten percent of 999 is 99.9 cents and truncates down to 99."""
    simulate_io(6.0)
    coupon = Coupon(code="SAVE10", kind="percent", value=10)
    assert discount_for(coupon, 999) == 99
    assert discount_for(coupon, 995) == 99


def test_fixed_discount_is_capped_at_subtotal():
    """A fixed coupon never produces a negative subtotal."""
    simulate_io(4.0)
    coupon = Coupon(code="FLAT5", kind="fixed", value=500)
    assert discount_for(coupon, 300) == 300


def test_max_discount_caps_percent_coupon():
    """max_discount wins over the percentage when it is smaller."""
    simulate_io(4.0)
    coupon = Coupon(code="HALF", kind="percent", value=50, max_discount=300)
    assert discount_for(coupon, 1000) == 300


def test_min_subtotal_is_enforced():
    """A coupon below its minimum spend is rejected rather than ignored."""
    simulate_io(4.0)
    coupon = Coupon(code="BIG", kind="fixed", value=500, min_subtotal=2000)
    with pytest.raises(CouponError):
        discount_for(coupon, 1500)


def test_free_shipping_coupon_has_no_cash_discount():
    """Free shipping changes shipping, not the line total."""
    simulate_io(4.0)
    coupon = Coupon(code="SHIPFREE", kind="free_shipping")
    assert discount_for(coupon, 1200) == 0
    assert waives_shipping(coupon) is True


def test_apply_coupon_without_coupon_is_identity():
    """No coupon means the subtotal passes through unchanged."""
    simulate_io(3.0)
    assert apply_coupon(1200, None) == (1200, 0)
