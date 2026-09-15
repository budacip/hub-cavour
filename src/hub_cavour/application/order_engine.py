"""Application service coordinating catalog, aggregate and repository."""

from __future__ import annotations

from collections.abc import Callable

from hub_cavour.application.commands import (
    AddItem,
    ChangeQuantity,
    ConfirmOrder,
    CreateOrder,
    RemoveItem,
    SetItemNote,
)
from hub_cavour.application.idempotency import command_fingerprint
from hub_cavour.domain.catalog import InMemoryCatalog
from hub_cavour.domain.errors import ModifierNotAllowed
from hub_cavour.domain.orders import ModifierSnapshot, Order, OrderItem
from hub_cavour.infrastructure.in_memory_repository import InMemoryOrderRepository


class OrderEngine:
    def __init__(
        self,
        catalog: InMemoryCatalog,
        orders: InMemoryOrderRepository,
    ) -> None:
        self._catalog = catalog
        self._orders = orders

    def create_order(self, command: CreateOrder) -> Order:
        return self._execute(command, lambda: self._orders.create(Order(command.order_id)))

    def add_item(self, command: AddItem) -> Order:
        def operation() -> Order:
            order = self._orders.get_at_version(
                command.order_id, command.expected_version
            )
            product = self._catalog.get(command.product_id)
            if command.modifier_ids and command.modifier_selections:
                raise ModifierNotAllowed(
                    "Use modifier_ids or modifier_selections, not both"
                )
            selections = (
                tuple(
                    (selection.modifier_id, selection.quantity)
                    for selection in command.modifier_selections
                )
                if command.modifier_selections
                else tuple((modifier_id, 1) for modifier_id in command.modifier_ids)
            )
            modifiers = product.resolve_modifier_quantities(selections)
            item = OrderItem(
                id=command.item_id,
                product_id=product.id,
                product_name=product.name,
                base_unit_price=product.price,
                quantity=command.quantity,
                modifiers=tuple(
                    ModifierSnapshot(
                        modifier_id=modifier.id,
                        name=modifier.name,
                        price_delta=modifier.price_delta,
                        quantity=quantity,
                    )
                    for modifier, quantity in modifiers
                ),
            )
            order.add_item(item)
            return self._orders.save(order, command.expected_version)

        return self._execute(command, operation)

    def remove_item(self, command: RemoveItem) -> Order:
        def operation() -> Order:
            order = self._orders.get_at_version(
                command.order_id, command.expected_version
            )
            order.remove_item(command.item_id)
            return self._orders.save(order, command.expected_version)

        return self._execute(command, operation)

    def set_item_note(self, command: SetItemNote) -> Order:
        def operation() -> Order:
            order = self._orders.get_at_version(
                command.order_id, command.expected_version
            )
            order.set_item_note(command.item_id, command.note)
            return self._orders.save(order, command.expected_version)

        return self._execute(command, operation)

    def change_quantity(self, command: ChangeQuantity) -> Order:
        def operation() -> Order:
            order = self._orders.get_at_version(
                command.order_id, command.expected_version
            )
            order.change_quantity(command.item_id, command.quantity)
            return self._orders.save(order, command.expected_version)

        return self._execute(command, operation)

    def confirm_order(self, command: ConfirmOrder) -> Order:
        def operation() -> Order:
            order = self._orders.get_at_version(
                command.order_id, command.expected_version
            )
            order.confirm()
            return self._orders.save(order, command.expected_version)

        return self._execute(command, operation)

    def get_order(self, order_id: str) -> Order:
        return self._orders.get(order_id)

    def _execute(self, command: object, operation: Callable[[], Order]) -> Order:
        command_id = getattr(command, "command_id")
        fingerprint = command_fingerprint(command)
        return self._orders.execute_once(command_id, fingerprint, operation)
