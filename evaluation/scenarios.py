"""Code changes to evaluate test selection against.

Each scenario is one exact string replacement in the demo app, so applying and
reverting is unambiguous and leaves no residue. Which tests a scenario breaks
is deliberately not written down here: the harness measures it by running the
whole suite. A hand-written expectation would be one more thing that can be
wrong, and it would be wrong in the direction that flatters the results.

The set covers the shapes a ranking has to handle: a change whose own tests
catch it, a change that only breaks a different module, a change that reaches
several modules at once, and a change that breaks nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass

APP = "demo_project/app"


@dataclass(frozen=True)
class Scenario:
    name: str
    shape: str
    description: str
    path: str
    old: str
    new: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="coupon_rounding",
        shape="direct and indirect",
        description="percent discount rounds half up instead of truncating",
        path=f"{APP}/coupon.py",
        old="    return (subtotal * percent) // 100",
        new="    return round(subtotal * percent / 100)",
    ),
    Scenario(
        name="coupon_cap_off_by_one",
        shape="direct",
        description="max_discount allows one cent more than it should",
        path=f"{APP}/coupon.py",
        old="        amount = min(amount, coupon.max_discount)",
        new="        amount = min(amount, coupon.max_discount + 1)",
    ),
    Scenario(
        name="coupon_floor_at_zero_removed",
        shape="direct",
        description="a fixed coupon is no longer capped at the subtotal",
        path=f"{APP}/coupon.py",
        old="    return min(amount, subtotal)",
        new="    return amount",
    ),
    Scenario(
        name="shipping_threshold",
        shape="direct",
        description="free shipping threshold moves one cent out of reach",
        path=f"{APP}/checkout.py",
        old="FREE_SHIPPING_THRESHOLD = 5_000",
        new="FREE_SHIPPING_THRESHOLD = 5_001",
    ),
    Scenario(
        name="tax_rate",
        shape="direct, several tests",
        description="tax rises from 7 to 8 percent",
        path=f"{APP}/checkout.py",
        old="TAX_BPS = 700",
        new="TAX_BPS = 800",
    ),
    Scenario(
        name="card_flat_fee",
        shape="indirect",
        description="the flat card fee changes, which moves every order total",
        path=f"{APP}/payment.py",
        old="FLAT_FEE = {CARD: 30, WALLET: 0, BANK_TRANSFER: 120}",
        new="FLAT_FEE = {CARD: 35, WALLET: 0, BANK_TRANSFER: 120}",
    ),
    Scenario(
        name="wallet_fee_rate",
        shape="direct, misleading name overlap",
        description="the wallet fee rate changes; the word fee appears all over checkout",
        path=f"{APP}/payment.py",
        old="FEE_BPS = {CARD: 290, WALLET: 150, BANK_TRANSFER: 0}",
        new="FEE_BPS = {CARD: 290, WALLET: 160, BANK_TRANSFER: 0}",
    ),
    Scenario(
        name="luhn_accepts_near_misses",
        shape="direct",
        description="the card checksum accepts numbers that are one off",
        path=f"{APP}/payment.py",
        old="    return total % 10 == 0",
        new="    return total % 10 <= 1",
    ),
    Scenario(
        name="email_tld_length",
        shape="direct, unrelated module",
        description="email validation demands a three letter top level domain",
        path=f"{APP}/profile.py",
        old=r'EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")',
        new=r'EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{3,}$")',
    ),
    Scenario(
        name="display_name_limit",
        shape="direct, unrelated module",
        description="the display name limit drops below a normal full name",
        path=f"{APP}/profile.py",
        old="MAX_DISPLAY_NAME = 32",
        new="MAX_DISPLAY_NAME = 8",
    ),
    Scenario(
        name="avatar_size_limit",
        shape="direct, slowest test",
        description="the avatar size limit falls below the size the test uploads",
        path=f"{APP}/profile.py",
        old="MAX_AVATAR_BYTES = 2 * 1024 * 1024",
        new="MAX_AVATAR_BYTES = 100 * 1024",
    ),
    Scenario(
        name="cart_stops_merging_lines",
        shape="direct, several tests",
        description="adding the same sku twice creates a second line",
        path=f"{APP}/cart.py",
        old="                item.quantity += quantity\n                return",
        new="                break",
    ),
    Scenario(
        name="benign_docstring",
        shape="benign",
        description="a docstring is reworded and nothing else changes",
        path=f"{APP}/coupon.py",
        old='    """Return (discounted_subtotal, discount_amount)."""',
        new='    """Return the subtotal after the coupon, and the amount taken off."""',
    ),
    Scenario(
        name="benign_constant_rename",
        shape="benign",
        description="a shipping constant gains an explanatory comment",
        path=f"{APP}/checkout.py",
        old="SHIPPING_FLAT = 500",
        new="SHIPPING_FLAT = 500  # cents, flat rate below the free shipping threshold",
    ),
)

BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}
