import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from app.cart import Cart, Product

WIDGET = Product(sku="widget", name="Widget", unit_price=1200, category="hardware")
GADGET = Product(sku="gadget", name="Gadget", unit_price=2500, category="hardware")
EBOOK = Product(sku="ebook", name="E-book", unit_price=999, category="digital")


@pytest.fixture
def widget():
    return WIDGET


@pytest.fixture
def gadget():
    return GADGET


@pytest.fixture
def ebook():
    return EBOOK


@pytest.fixture
def single_widget_cart():
    """Subtotal 1200, below the free shipping threshold."""
    cart = Cart()
    cart.add_item(WIDGET)
    return cart


@pytest.fixture
def threshold_cart():
    """Subtotal 5000, exactly on the free shipping threshold."""
    cart = Cart()
    cart.add_item(GADGET, 2)
    return cart


@pytest.fixture
def ebook_cart():
    """Subtotal 999, chosen so a percentage discount lands on a half cent."""
    cart = Cart()
    cart.add_item(EBOOK)
    return cart
