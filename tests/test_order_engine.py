from __future__ import annotations

import unittest

from hub_cavour.application.commands import (
    AddItem,
    ChangeQuantity,
    ConfirmOrder,
    CreateOrder,
)
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.domain.catalog import CatalogModifier, CatalogProduct, InMemoryCatalog
from hub_cavour.domain.errors import (
    EmptyOrder,
    IdempotencyConflict,
    InvalidMoney,
    InvalidOrderTransition,
    InvalidQuantity,
    ModifierNotAllowed,
    VersionConflict,
)
from hub_cavour.domain.money import Money
from hub_cavour.domain.orders import OrderStatus
from hub_cavour.infrastructure.in_memory_repository import InMemoryOrderRepository


class OrderEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = InMemoryCatalog(
            (
                CatalogProduct(
                    id="coppa-cavour",
                    name="Coppa Cavour",
                    price=Money(650),
                    modifiers=(
                        CatalogModifier("panna", "Panna montata", Money(80)),
                        CatalogModifier("senza-granella", "Senza granella", Money(0)),
                    ),
                ),
            )
        )
        self.repository = InMemoryOrderRepository()
        self.engine = OrderEngine(self.catalog, self.repository)

    def create_order(self, command_id: str = "cmd-create"):
        return self.engine.create_order(CreateOrder(command_id, "order-1"))

    def add_coppa(
        self,
        *,
        command_id: str = "cmd-add",
        expected_version: int = 0,
        quantity: int = 1,
        modifier_ids: tuple[str, ...] = (),
    ):
        return self.engine.add_item(
            AddItem(
                command_id=command_id,
                order_id="order-1",
                expected_version=expected_version,
                item_id="item-1",
                product_id="coppa-cavour",
                quantity=quantity,
                modifier_ids=modifier_ids,
            )
        )

    def test_money_rejects_float_values(self) -> None:
        with self.assertRaises(InvalidMoney):
            Money(6.50)  # type: ignore[arg-type]

    def test_create_order_starts_as_empty_draft_at_version_zero(self) -> None:
        order = self.create_order()
        self.assertEqual(OrderStatus.DRAFT, order.status)
        self.assertEqual(0, order.version)
        self.assertEqual(Money.zero(), order.total)

    def test_total_includes_quantity_and_modifier_snapshots(self) -> None:
        self.create_order()
        order = self.add_coppa(quantity=2, modifier_ids=("panna",))
        self.assertEqual(Money(1460), order.total)
        self.assertEqual(Money(730), order.items[0].unit_price)
        self.assertEqual("Panna montata", order.items[0].modifiers[0].name)

    def test_price_snapshot_does_not_change_when_catalog_changes(self) -> None:
        self.create_order()
        self.add_coppa()
        self.catalog.put(CatalogProduct("coppa-cavour", "Coppa Cavour", Money(900)))
        stored = self.engine.get_order("order-1")
        self.assertEqual(Money(650), stored.items[0].base_unit_price)
        self.assertEqual(Money(650), stored.total)

    def test_change_quantity_recalculates_total_and_increments_version(self) -> None:
        self.create_order()
        self.add_coppa(quantity=1)
        order = self.engine.change_quantity(
            ChangeQuantity("cmd-quantity", "order-1", 1, "item-1", 3)
        )
        self.assertEqual(2, order.version)
        self.assertEqual(3, order.items[0].quantity)
        self.assertEqual(Money(1950), order.total)

    def test_non_positive_quantities_are_rejected_without_saving(self) -> None:
        self.create_order()
        with self.assertRaises(InvalidQuantity):
            self.add_coppa(quantity=0)
        self.assertEqual(0, self.engine.get_order("order-1").version)

    def test_non_positive_quantity_change_is_rejected_without_saving(self) -> None:
        self.create_order()
        self.add_coppa()
        with self.assertRaises(InvalidQuantity):
            self.engine.change_quantity(
                ChangeQuantity("cmd-bad-quantity", "order-1", 1, "item-1", 0)
            )
        stored = self.engine.get_order("order-1")
        self.assertEqual(1, stored.version)
        self.assertEqual(1, stored.items[0].quantity)

    def test_modifier_not_allowed_is_rejected_without_saving(self) -> None:
        self.create_order()
        with self.assertRaises(ModifierNotAllowed):
            self.add_coppa(modifier_ids=("inventato",))
        self.assertEqual(0, self.engine.get_order("order-1").version)

    def test_duplicate_modifier_is_rejected_without_saving(self) -> None:
        self.create_order()
        with self.assertRaises(ModifierNotAllowed):
            self.add_coppa(modifier_ids=("panna", "panna"))
        self.assertEqual(0, self.engine.get_order("order-1").version)

    def test_confirm_empty_order_is_invalid(self) -> None:
        self.create_order()
        with self.assertRaises(EmptyOrder):
            self.engine.confirm_order(ConfirmOrder("cmd-confirm", "order-1", 0))

    def test_confirmed_order_cannot_be_changed_or_confirmed_again(self) -> None:
        self.create_order()
        self.add_coppa()
        confirmed = self.engine.confirm_order(ConfirmOrder("cmd-confirm", "order-1", 1))
        self.assertEqual(OrderStatus.CONFIRMED, confirmed.status)
        with self.assertRaises(InvalidOrderTransition):
            self.engine.change_quantity(
                ChangeQuantity("cmd-late-change", "order-1", 2, "item-1", 2)
            )
        with self.assertRaises(InvalidOrderTransition):
            self.engine.add_item(
                AddItem(
                    "cmd-late-add",
                    "order-1",
                    2,
                    "item-2",
                    "coppa-cavour",
                    1,
                )
            )
        with self.assertRaises(InvalidOrderTransition):
            self.engine.confirm_order(ConfirmOrder("cmd-confirm-again", "order-1", 2))

    def test_stale_expected_version_is_rejected(self) -> None:
        self.create_order()
        self.add_coppa()
        with self.assertRaises(VersionConflict) as context:
            self.engine.change_quantity(
                ChangeQuantity("cmd-stale", "order-1", 0, "item-1", 2)
            )
        self.assertEqual(0, context.exception.expected)
        self.assertEqual(1, context.exception.actual)

    def test_exact_retry_returns_original_result_without_duplicate_execution(self) -> None:
        self.create_order()
        command = AddItem(
            "cmd-add-once", "order-1", 0, "item-1", "coppa-cavour", 1
        )
        first = self.engine.add_item(command)
        retry = self.engine.add_item(command)
        stored = self.engine.get_order("order-1")
        self.assertEqual(1, first.version)
        self.assertEqual(first, retry)
        self.assertEqual(1, stored.version)
        self.assertEqual(1, len(stored.items))

    def test_command_id_cannot_be_reused_with_different_payload(self) -> None:
        self.create_order()
        self.add_coppa(command_id="same-command")
        with self.assertRaises(IdempotencyConflict):
            self.engine.change_quantity(
                ChangeQuantity("same-command", "order-1", 1, "item-1", 2)
            )


if __name__ == "__main__":
    unittest.main()
