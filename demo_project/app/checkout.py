"""Order assembly.

checkout depends on cart, coupon and payment, so a change confined to one of
those modules still moves the numbers asserted here. That indirect coupling is
what a filename-based test filter misses.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import payment
from app.cart import Cart, CartError
from app.coupon import Coupon, apply_coupon, waives_shipping

SHIPPING_FLAT = 500
FREE_SHIPPING_THRESHOLD = 5_000
TAX_BPS = 700


class CheckoutError(Exception):
    """Raised when an order cannot be built."""


@dataclass(frozen=True)
class Order:
    subtotal: int
    discount: int
    shipping: int
    tax: int
    payment_fee: int
    total: int
    method: str

    def as_breakdown(self) -> dict[str, int]:
        return {
            "subtotal": self.subtotal,
            "discount": self.discount,
            "shipping": self.shipping,
            "tax": self.tax,
            "payment_fee": self.payment_fee,
            "total": self.total,
        }


def shipping_cost(discounted_subtotal: int, coupon: Coupon | None) -> int:
    if waives_shipping(coupon):
        return 0
    if discounted_subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0
    return SHIPPING_FLAT


def tax_for(taxable: int) -> int:
    return (taxable * TAX_BPS) // 10_000


def build_order(cart: Cart, coupon: Coupon | None = None, method: str = payment.CARD) -> Order:
    if cart.is_empty():
        raise CheckoutError("cannot check out an empty cart")
    if method not in payment.VALID_METHODS:
        raise CheckoutError(f"unknown payment method: {method}")

    subtotal = cart.subtotal()
    discounted, discount = apply_coupon(subtotal, coupon)
    shipping = shipping_cost(discounted, coupon)
    tax = tax_for(discounted + shipping)
    fee = payment.processing_fee(method, discounted + shipping + tax)
    total = discounted + shipping + tax + fee

    return Order(
        subtotal=subtotal,
        discount=discount,
        shipping=shipping,
        tax=tax,
        payment_fee=fee,
        total=total,
        method=method,
    )


def quote_totals(cart: Cart, coupons: list[Coupon | None]) -> list[int]:
    """Compare several coupons against the same cart."""
    if cart.is_empty():
        raise CartError("cannot quote an empty cart")
    return [build_order(cart, coupon).total for coupon in coupons]
