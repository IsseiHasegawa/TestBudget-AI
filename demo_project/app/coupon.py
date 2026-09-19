"""Coupon rules and discount calculation.

The rounding policy below is the interesting part for TestBudget AI: changing it
moves checkout totals even though checkout.py itself is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

PERCENT = "percent"
FIXED = "fixed"
FREE_SHIPPING = "free_shipping"

VALID_KINDS = {PERCENT, FIXED, FREE_SHIPPING}


class CouponError(Exception):
    """Raised when a coupon cannot be applied."""


@dataclass(frozen=True)
class Coupon:
    code: str
    kind: str
    value: int = 0
    min_subtotal: int = 0
    max_discount: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise CouponError(f"unknown coupon kind: {self.kind}")
        if self.kind == PERCENT and not 0 <= self.value <= 100:
            raise CouponError("percent coupon must be between 0 and 100")
        if self.value < 0:
            raise CouponError("coupon value must not be negative")


def _round_percent(subtotal: int, percent: int) -> int:
    """Convert a percentage of `subtotal` into whole cents.

    Truncating toward zero always favours the store by at most one cent. A PR
    that switches this to banker's rounding is the canonical demo change.
    """
    return (subtotal * percent) // 100


def discount_for(coupon: Coupon, subtotal: int) -> int:
    if subtotal < 0:
        raise CouponError("subtotal must not be negative")
    if subtotal < coupon.min_subtotal:
        raise CouponError(
            f"coupon {coupon.code} requires a subtotal of at least {coupon.min_subtotal}"
        )

    if coupon.kind == PERCENT:
        amount = _round_percent(subtotal, coupon.value)
    elif coupon.kind == FIXED:
        amount = coupon.value
    else:
        amount = 0

    if coupon.max_discount is not None:
        amount = min(amount, coupon.max_discount)
    return min(amount, subtotal)


def apply_coupon(subtotal: int, coupon: Coupon | None) -> tuple[int, int]:
    """Return (discounted_subtotal, discount_amount)."""
    if coupon is None:
        return subtotal, 0
    discount = discount_for(coupon, subtotal)
    return subtotal - discount, discount


def waives_shipping(coupon: Coupon | None) -> bool:
    return coupon is not None and coupon.kind == FREE_SHIPPING
