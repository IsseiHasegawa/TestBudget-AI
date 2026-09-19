import pytest

from app.payment import (
    BANK_TRANSFER,
    CARD,
    WALLET,
    PaymentError,
    authorize,
    luhn_checksum_ok,
    processing_fee,
    validate_card,
)
from support import simulate_io

VALID_CARD = "4242424242424242"


def test_card_fee_is_percentage_plus_flat():
    """Card fees are 2.9 percent in basis points plus 30 cents."""
    assert processing_fee(CARD, 5350) == 185
    assert processing_fee(WALLET, 5350) == 80


def test_bank_transfer_fee_is_flat_only():
    """Bank transfer has no percentage component."""
    assert processing_fee(BANK_TRANSFER, 10_000) == 120


def test_unknown_method_is_rejected():
    """An unrecognised method never falls through to a default fee."""
    with pytest.raises(PaymentError):
        processing_fee("crypto", 1000)


def test_expired_card_is_rejected():
    """A card whose expiry is before the reference month fails validation."""
    simulate_io(0.10)
    assert luhn_checksum_ok(VALID_CARD) is True
    assert luhn_checksum_ok("4242424242424241") is False
    validate_card(VALID_CARD, 12, 2030, today=(2026, 9))
    with pytest.raises(PaymentError):
        validate_card(VALID_CARD, 8, 2026, today=(2026, 9))


@pytest.mark.slow
def test_authorize_contacts_gateway():
    """Authorization round trip, standing in for a real gateway call."""
    simulate_io(1.20)
    auth = authorize(CARD, 5350, reference="order-1")
    assert auth.fee == 185
    assert auth.captured_total == 5535
    with pytest.raises(PaymentError):
        authorize(CARD, 0)
