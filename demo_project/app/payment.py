"""Payment method validation and fees."""

from __future__ import annotations

from dataclasses import dataclass

CARD = "card"
WALLET = "wallet"
BANK_TRANSFER = "bank_transfer"

VALID_METHODS = {CARD, WALLET, BANK_TRANSFER}

# Basis points, so the fee math stays in integers.
FEE_BPS = {CARD: 290, WALLET: 150, BANK_TRANSFER: 0}
FLAT_FEE = {CARD: 30, WALLET: 0, BANK_TRANSFER: 120}


class PaymentError(Exception):
    """Raised when a payment cannot be authorized."""


@dataclass(frozen=True)
class Authorization:
    method: str
    amount: int
    fee: int
    reference: str

    @property
    def captured_total(self) -> int:
        return self.amount + self.fee


def processing_fee(method: str, amount: int) -> int:
    if method not in VALID_METHODS:
        raise PaymentError(f"unknown payment method: {method}")
    if amount < 0:
        raise PaymentError("amount must not be negative")
    if amount == 0:
        return 0
    return (amount * FEE_BPS[method]) // 10_000 + FLAT_FEE[method]


def luhn_checksum_ok(number: str) -> bool:
    digits = [int(ch) for ch in number if ch.isdigit()]
    if len(digits) < 12:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card(number: str, exp_month: int, exp_year: int, today: tuple[int, int]) -> None:
    """Raise PaymentError unless the card is structurally valid and unexpired.

    `today` is (year, month) so the demo tests never depend on the wall clock.
    """
    if not luhn_checksum_ok(number):
        raise PaymentError("card number failed checksum")
    if not 1 <= exp_month <= 12:
        raise PaymentError("expiry month out of range")
    current_year, current_month = today
    if (exp_year, exp_month) < (current_year, current_month):
        raise PaymentError("card expired")


def authorize(method: str, amount: int, reference: str = "demo-ref") -> Authorization:
    if amount <= 0:
        raise PaymentError("cannot authorize a non-positive amount")
    return Authorization(
        method=method,
        amount=amount,
        fee=processing_fee(method, amount),
        reference=reference,
    )
