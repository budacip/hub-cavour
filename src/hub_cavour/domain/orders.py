"""Order aggregate and price snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from hub_cavour.domain.errors import (
    EmptyOrder,
    InvalidItemPrice,
    InvalidOrderTransition,
    InvalidQuantity,
    ItemNotFound,
)
from hub_cavour.domain.money import Money


class OrderStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class ModifierSnapshot:
    modifier_id: str
    name: str
    price_delta: Money


@dataclass(slots=True)
class OrderItem:
    id: str
    product_id: str
    product_name: str
    base_unit_price: Money
    quantity: int
    modifiers: tuple[ModifierSnapshot, ...] = ()

    def __post_init__(self) -> None:
        self.set_quantity(self.quantity)
        if self.unit_price.cents < 0:
            raise InvalidItemPrice("An order item unit price cannot be negative")

    @property
    def unit_price(self) -> Money:
        result = self.base_unit_price
        for modifier in self.modifiers:
            result = result + modifier.price_delta
        return result

    @property
    def total(self) -> Money:
        return self.unit_price * self.quantity

    def set_quantity(self, quantity: int) -> None:
        if type(quantity) is not int or quantity <= 0:
            raise InvalidQuantity("Item quantity must be a positive integer")
        self.quantity = quantity


@dataclass(slots=True)
class Order:
    id: str
    status: OrderStatus = OrderStatus.DRAFT
    version: int = 0
    currency: str = "EUR"
    items: list[OrderItem] = field(default_factory=list)

    @property
    def total(self) -> Money:
        result = Money.zero(self.currency)
        for item in self.items:
            result = result + item.total
        return result

    def add_item(self, item: OrderItem) -> None:
        self._require_draft("add items")
        if item.base_unit_price.currency != self.currency:
            raise InvalidItemPrice(
                f"Order currency is {self.currency}, item currency is "
                f"{item.base_unit_price.currency}"
            )
        if any(existing.id == item.id for existing in self.items):
            raise InvalidOrderTransition(f"Item id {item.id!r} already exists")
        self.items.append(item)

    def change_quantity(self, item_id: str, quantity: int) -> None:
        self._require_draft("change quantities")
        for item in self.items:
            if item.id == item_id:
                item.set_quantity(quantity)
                return
        raise ItemNotFound(f"Item {item_id!r} was not found in order {self.id!r}")

    def confirm(self) -> None:
        self._require_draft("confirm the order")
        if not self.items:
            raise EmptyOrder("An empty order cannot be confirmed")
        self.status = OrderStatus.CONFIRMED

    def _require_draft(self, action: str) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise InvalidOrderTransition(
                f"Cannot {action} while order status is {self.status.value!r}"
            )
