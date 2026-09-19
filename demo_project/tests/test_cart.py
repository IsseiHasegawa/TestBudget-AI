import pytest

from app.cart import Cart, CartError, Product
from support import simulate_io


def test_add_item_appends_new_product(widget):
    """A product not yet in the cart becomes a new line."""
    cart = Cart()
    cart.add_item(widget)
    assert cart.item_count() == 1
    assert cart.subtotal() == 1200


def test_add_item_merges_matching_sku(widget):
    """Adding the same sku twice increases quantity instead of duplicating lines."""
    cart = Cart()
    cart.add_item(widget, 2)
    cart.add_item(widget, 3)
    assert len(cart.items) == 1
    assert cart.item_count() == 5


def test_add_item_rejects_non_positive_quantity(widget):
    """Quantity zero or below is a caller error, not a silent no-op."""
    cart = Cart()
    with pytest.raises(CartError):
        cart.add_item(widget, 0)


def test_set_quantity_to_zero_removes_line(widget, gadget):
    """Setting a quantity of zero drops the line entirely."""
    cart = Cart()
    cart.add_item(widget)
    cart.add_item(gadget)
    cart.set_quantity("widget", 0)
    assert [item.product.sku for item in cart.items] == ["gadget"]


def test_remove_unknown_sku_raises(widget):
    """Removing something that was never added is an error."""
    cart = Cart()
    cart.add_item(widget)
    with pytest.raises(CartError):
        cart.remove_item("missing")


def test_subtotal_reflects_quantity_changes(widget, ebook):
    """Subtotal recomputes after quantities move."""
    simulate_io(0.15)
    cart = Cart()
    cart.add_item(widget, 2)
    cart.add_item(ebook, 1)
    assert cart.subtotal() == 1200 * 2 + 999
    cart.set_quantity("widget", 1)
    assert cart.subtotal() == 1200 + 999
    assert cart.categories() == {"hardware", "digital"}
