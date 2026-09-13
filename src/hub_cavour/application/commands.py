"""Immutable command payloads accepted by the Order Engine."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateOrder:
    command_id: str
    order_id: str


@dataclass(frozen=True, slots=True)
class AddItem:
    command_id: str
    order_id: str
    expected_version: int
    item_id: str
    product_id: str
    quantity: int
    modifier_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChangeQuantity:
    command_id: str
    order_id: str
    expected_version: int
    item_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class ConfirmOrder:
    command_id: str
    order_id: str
    expected_version: int
