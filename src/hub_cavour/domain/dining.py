"""Dining-room domain: tables, service sessions and immutable submissions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hub_cavour.domain.errors import (
    InvalidIdentifier,
    InvalidModifierQuantity,
    InvalidNote,
    InvalidQuantity,
    InvalidSubmissionSequence,
    InvalidTableSessionTransition,
    InvalidVersion,
    OrderAlreadyAssigned,
    OrderAlreadySubmitted,
    OrderNotAssignedToSession,
)
from hub_cavour.domain.money import Money


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIdentifier(f"{label} must be a non-empty string")


def _require_version(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise InvalidVersion(f"{label} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class Table:
    id: str
    name: str

    def __post_init__(self) -> None:
        _require_id(self.id, "Table id")
        _require_id(self.name, "Table name")


class TableSessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SubmittedModifierSnapshot:
    modifier_id: str
    name: str
    price_delta: Money
    quantity: int

    def __post_init__(self) -> None:
        _require_id(self.modifier_id, "Modifier id")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise InvalidModifierQuantity(
                "Submitted modifier quantity must be a positive integer"
            )


@dataclass(frozen=True, slots=True)
class SubmittedOrderItemSnapshot:
    item_id: str
    product_id: str
    product_name: str
    base_unit_price: Money
    quantity: int
    modifiers: tuple[SubmittedModifierSnapshot, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        _require_id(self.item_id, "Order item id")
        _require_id(self.product_id, "Product id")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise InvalidQuantity(
                "Submitted item quantity must be a positive integer"
            )
        if not isinstance(self.note, str):
            raise InvalidNote("Submitted item note must be a string")
        for modifier in self.modifiers:
            if modifier.price_delta.currency != self.base_unit_price.currency:
                raise InvalidTableSessionTransition(
                    "Submitted item and modifier currencies must match"
                )

    @property
    def unit_price(self) -> Money:
        result = self.base_unit_price
        for modifier in self.modifiers:
            result += modifier.price_delta * modifier.quantity
        return result

    @property
    def total(self) -> Money:
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class SubmittedOrderSnapshot:
    order_id: str
    order_version: int
    currency: str
    items: tuple[SubmittedOrderItemSnapshot, ...]

    def __post_init__(self) -> None:
        _require_id(self.order_id, "Order id")
        _require_version(self.order_version, "Order version")
        Money.zero(self.currency)
        if not self.items:
            raise InvalidTableSessionTransition(
                "A submitted order snapshot cannot be empty"
            )
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise InvalidTableSessionTransition(
                "Submitted order item ids must be unique"
            )
        if any(item.base_unit_price.currency != self.currency for item in self.items):
            raise InvalidTableSessionTransition(
                "Submitted order item currencies must match the order currency"
            )

    @property
    def total(self) -> Money:
        result = Money.zero(self.currency)
        for item in self.items:
            result += item.total
        return result


@dataclass(frozen=True, slots=True)
class OrderSubmission:
    sequence: int
    order: SubmittedOrderSnapshot

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise InvalidSubmissionSequence(
                "Submission sequence must be a positive integer"
            )

    @property
    def order_id(self) -> str:
        return self.order.order_id

    @property
    def order_version(self) -> int:
        return self.order.order_version


@dataclass(slots=True)
class TableSession:
    id: str
    table_id: str
    status: TableSessionStatus = TableSessionStatus.OPEN
    version: int = 0
    assigned_order_ids: tuple[str, ...] = ()
    submissions: tuple[OrderSubmission, ...] = ()

    def __post_init__(self) -> None:
        self.validate()

    def assign_order(self, order_id: str) -> None:
        self._require_open("assign an order")
        _require_id(order_id, "Order id")
        if order_id in self.assigned_order_ids:
            raise OrderAlreadyAssigned(
                f"Order {order_id!r} is already assigned to this session"
            )
        self.assigned_order_ids += (order_id,)

    def add_submission(self, order: SubmittedOrderSnapshot) -> None:
        self._require_open("add an order submission")
        if order.order_id not in self.assigned_order_ids:
            raise OrderNotAssignedToSession(
                f"Order {order.order_id!r} is not assigned to session {self.id!r}"
            )
        if any(existing.order_id == order.order_id for existing in self.submissions):
            raise OrderAlreadySubmitted(
                f"Order {order.order_id!r} was already submitted"
            )
        self.submissions += (
            OrderSubmission(sequence=len(self.submissions) + 1, order=order),
        )

    def close(self) -> None:
        self._require_open("close the table session")
        self.status = TableSessionStatus.CLOSED

    def validate(self) -> None:
        _require_id(self.id, "Table session id")
        _require_id(self.table_id, "Table id")
        _require_version(self.version, "Table session version")
        if not isinstance(self.status, TableSessionStatus):
            raise InvalidTableSessionTransition("Invalid table session status")
        for order_id in self.assigned_order_ids:
            _require_id(order_id, "Assigned order id")
        if len(self.assigned_order_ids) != len(set(self.assigned_order_ids)):
            raise OrderAlreadyAssigned("Assigned order ids must be unique")
        expected_sequences = tuple(range(1, len(self.submissions) + 1))
        actual_sequences = tuple(item.sequence for item in self.submissions)
        if actual_sequences != expected_sequences:
            raise InvalidSubmissionSequence(
                "Submission sequences must be contiguous and start at one"
            )
        submitted_ids = tuple(item.order_id for item in self.submissions)
        if len(submitted_ids) != len(set(submitted_ids)):
            raise OrderAlreadySubmitted("Submitted order ids must be unique")
        if any(order_id not in self.assigned_order_ids for order_id in submitted_ids):
            raise OrderNotAssignedToSession(
                "Every submitted order must be assigned to the session"
            )

    def _require_open(self, action: str) -> None:
        if self.status is not TableSessionStatus.OPEN:
            raise InvalidTableSessionTransition(
                f"Cannot {action} while table session status is {self.status.value!r}"
            )
