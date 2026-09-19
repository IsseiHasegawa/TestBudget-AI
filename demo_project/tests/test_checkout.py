import pytest

from app import payment
from app.cart import Cart
from app.checkout import CheckoutError, build_order, quote_totals, shipping_cost, tax_for
from app.coupon import Coupon
from support import simulate_io


def test_order_breakdown_without_coupon(single_widget_cart):
    """Baseline order: flat shipping, tax on subtotal plus shipping, card fee."""
    simulate_io(0.20)
    order = build_order(single_widget_cart)
    assert order.as_breakdown() == {
        "subtotal": 1200,
        "discount": 0,
        "shipping": 500,
        "tax": 119,
        "payment_fee": 82,
        "total": 1901,
    }


def test_percent_coupon_changes_total(ebook_cart):
    """A discount computed in coupon.py flows all the way into the total."""
    simulate_io(0.30)
    coupon = Coupon(code="SAVE10", kind="percent", value=10)
    order = build_order(ebook_cart, coupon)
    assert order.discount == 99
    assert order.tax == 98
    assert order.total == 1571


def test_free_shipping_threshold_removes_shipping(threshold_cart):
    """Reaching the threshold drops the flat shipping charge."""
    simulate_io(0.20)
    order = build_order(threshold_cart)
    assert order.shipping == 0
    assert order.total == 5535


def test_fixed_coupon_can_push_order_back_under_threshold(threshold_cart):
    """Discounting below the threshold reinstates shipping."""
    simulate_io(0.15)
    coupon = Coupon(code="FLAT10", kind="fixed", value=1000)
    order = build_order(threshold_cart, coupon)
    assert order.shipping == 500
    assert order.total == 4984


def test_payment_method_changes_fee_only(threshold_cart):
    """Switching to bank transfer changes the fee and nothing above it."""
    order = build_order(threshold_cart, method=payment.BANK_TRANSFER)
    assert order.tax == 350
    assert order.payment_fee == 120
    assert order.total == 5470


def test_empty_cart_cannot_check_out():
    """An empty cart is refused before any pricing runs."""
    with pytest.raises(CheckoutError):
        build_order(Cart())


def test_quote_totals_compares_coupons(single_widget_cart):
    """Quoting several coupons against one cart keeps each total independent."""
    simulate_io(0.35)
    coupons = [None, Coupon(code="SAVE10", kind="percent", value=10), Coupon(code="SHIPFREE", kind="free_shipping")]
    assert quote_totals(single_widget_cart, coupons) == [1901, 1769, 1351]
    assert shipping_cost(5000, None) == 0
    assert tax_for(1700) == 119
