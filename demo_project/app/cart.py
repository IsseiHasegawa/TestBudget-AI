"""Shopping cart primitives.

Amounts are integer cents everywhere in this demo so that discount rounding is
an explicit decision rather than a floating point accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class CartError(Exception):
    """Raised when a cart operation is not valid."""


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    unit_price: int
    category: str = "general"

    def __post_init__(self) -> None:
        if self.unit_price < 0:
            raise CartError(f"negative unit price for {self.sku}")


@dataclass
class CartItem:
    product: Product
    quantity: int

    def line_total(self) -> int:
        return self.product.unit_price * self.quantity


@dataclass
class Cart:
    items: list[CartItem] = field(default_factory=list)

    def add_item(self, product: Product, quantity: int = 1) -> None:
        if quantity <= 0:
            raise CartError("quantity must be positive")
        for item in self.items:
            if item.product.sku == product.sku:
                item.quantity += quantity
                return
        self.items.append(CartItem(product=product, quantity=quantity))

    def set_quantity(self, sku: str, quantity: int) -> None:
        if quantity < 0:
            raise CartError("quantity must not be negative")
        if quantity == 0:
            self.remove_item(sku)
            return
        for item in self.items:
            if item.product.sku == sku:
                item.quantity = quantity
                return
        raise CartError(f"unknown sku: {sku}")

    def remove_item(self, sku: str) -> None:
        before = len(self.items)
        self.items = [item for item in self.items if item.product.sku != sku]
        if len(self.items) == before:
            raise CartError(f"unknown sku: {sku}")

    def subtotal(self) -> int:
        return sum(item.line_total() for item in self.items)

    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    def categories(self) -> set[str]:
        return {item.product.category for item in self.items}

    def is_empty(self) -> bool:
        return not self.items
