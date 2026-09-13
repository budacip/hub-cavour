from __future__ import annotations

import unittest

from hub_cavour.application.commands import (
    AddItem,
    ChangeQuantity,
    ConfirmOrder,
    CreateOrder,
    ModifierSelection,
    RemoveItem,
    SetItemNote,
)
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.domain.catalog import CatalogModifier, CatalogProduct, InMemoryCatalog
from hub_cavour.domain.errors import (
    EmptyOrder,
    IdempotencyConflict,
    InvalidModifierQuantity,
    InvalidMoney,
    InvalidNote,
    InvalidOrderTransition,
    InvalidQuantity,
    ItemNotFound,
    ModifierNotAllowed,
    VersionConflict,
)
from hub_cavour.domain.money import Money
from hub_cavour.domain.orders import ModifierSnapshot, OrderStatus
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
        item_id: str = "item-1",
        modifier_ids: tuple[str, ...] = (),
        modifier_selections: tuple[ModifierSelection, ...] = (),
    ):
        return self.engine.add_item(
            AddItem(
                command_id=command_id,
                order_id="order-1",
                expected_version=expected_version,
                item_id=item_id,
                product_id="coppa-cavour",
                quantity=quantity,
                modifier_ids=modifier_ids,
                modifier_selections=modifier_selections,
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

    def test_modifier_quantities_are_priced_and_snapshotted(self) -> None:
        self.create_order()
        order = self.add_coppa(
            quantity=2,
            modifier_selections=(ModifierSelection("panna", 3),),
        )

        self.assertEqual(Money(1780), order.total)
        self.assertEqual(3, order.items[0].modifiers[0].quantity)
        self.assertEqual(Money(890), order.items[0].unit_price)

    def test_invalid_modifier_quantity_is_rejected_without_saving(self) -> None:
        self.create_order()
        with self.assertRaises(InvalidModifierQuantity):
            self.add_coppa(
                modifier_selections=(ModifierSelection("panna", 0),),
            )
        self.assertEqual(0, self.engine.get_order("order-1").version)

    def test_modifier_snapshot_rejects_invalid_quantity(self) -> None:
        with self.assertRaises(InvalidModifierQuantity):
            ModifierSnapshot("panna", "Panna montata", Money(80), 0)

    def test_legacy_and_quantity_modifier_inputs_cannot_be_mixed(self) -> None:
        self.create_order()
        with self.assertRaises(ModifierNotAllowed):
            self.add_coppa(
                modifier_ids=("panna",),
                modifier_selections=(ModifierSelection("panna", 2),),
            )
        self.assertEqual(0, self.engine.get_order("order-1").version)

    def test_remove_item_updates_total_and_version(self) -> None:
        self.create_order()
        self.add_coppa(quantity=2)
        self.add_coppa(
            command_id="cmd-add-second",
            expected_version=1,
            item_id="item-2",
        )

        order = self.engine.remove_item(
            RemoveItem("cmd-remove", "order-1", 2, "item-1")
        )

        self.assertEqual(3, order.version)
        self.assertEqual(["item-2"], [item.id for item in order.items])
        self.assertEqual(Money(650), order.total)

    def test_item_note_can_be_added_and_modified(self) -> None:
        self.create_order()
        self.add_coppa()

        added = self.engine.set_item_note(
            SetItemNote("cmd-note-add", "order-1", 1, "item-1", "Poco zucchero")
        )
        modified = self.engine.set_item_note(
            SetItemNote("cmd-note-edit", "order-1", 2, "item-1", "Senza zucchero")
        )

        self.assertEqual("Poco zucchero", added.items[0].note)
        self.assertEqual("Senza zucchero", modified.items[0].note)
        self.assertEqual(3, modified.version)

    def test_invalid_note_is_rejected_without_saving(self) -> None:
        self.create_order()
        self.add_coppa()
        with self.assertRaises(InvalidNote):
            self.engine.set_item_note(
                SetItemNote(
                    "cmd-bad-note",
                    "order-1",
                    1,
                    "item-1",
                    42,  # type: ignore[arg-type]
                )
            )
        self.assertEqual(1, self.engine.get_order("order-1").version)

    def test_multiple_successive_operations_on_same_draft(self) -> None:
        self.create_order()
        self.add_coppa()
        self.add_coppa(
            command_id="cmd-add-second",
            expected_version=1,
            item_id="item-2",
        )
        self.engine.set_item_note(
            SetItemNote("cmd-note", "order-1", 2, "item-1", "Al tavolo")
        )
        self.engine.change_quantity(
            ChangeQuantity("cmd-quantity", "order-1", 3, "item-2", 2)
        )
        order = self.engine.remove_item(
            RemoveItem("cmd-remove", "order-1", 4, "item-1")
        )

        self.assertEqual(OrderStatus.DRAFT, order.status)
        self.assertEqual(5, order.version)
        self.assertEqual(2, order.items[0].quantity)
        self.assertEqual(Money(1300), order.total)

    def test_remove_and_note_are_invalid_after_confirmation(self) -> None:
        self.create_order()
        self.add_coppa()
        self.engine.confirm_order(ConfirmOrder("cmd-confirm", "order-1", 1))

        with self.assertRaises(InvalidOrderTransition):
            self.engine.remove_item(
                RemoveItem("cmd-late-remove", "order-1", 2, "item-1")
            )
        with self.assertRaises(InvalidOrderTransition):
            self.engine.set_item_note(
                SetItemNote("cmd-late-note", "order-1", 2, "item-1", "Nota")
            )

    def test_remove_and_note_require_existing_item(self) -> None:
        self.create_order()
        with self.assertRaises(ItemNotFound):
            self.engine.remove_item(
                RemoveItem("cmd-missing-remove", "order-1", 0, "missing")
            )
        with self.assertRaises(ItemNotFound):
            self.engine.set_item_note(
                SetItemNote("cmd-missing-note", "order-1", 0, "missing", "Nota")
            )

    def test_new_commands_honor_expected_version(self) -> None:
        self.create_order()
        self.add_coppa()
        with self.assertRaises(VersionConflict):
            self.engine.remove_item(
                RemoveItem("cmd-stale-remove", "order-1", 0, "item-1")
            )
        with self.assertRaises(VersionConflict):
            self.engine.set_item_note(
                SetItemNote("cmd-stale-note", "order-1", 0, "item-1", "Nota")
            )

    def test_remove_item_retry_is_idempotent(self) -> None:
        self.create_order()
        self.add_coppa()
        self.add_coppa(
            command_id="cmd-add-second",
            expected_version=1,
            item_id="item-2",
        )
        command = RemoveItem("cmd-remove-once", "order-1", 2, "item-2")

        first = self.engine.remove_item(command)
        retry = self.engine.remove_item(command)

        self.assertEqual(first, retry)
        self.assertEqual(3, self.engine.get_order("order-1").version)
        self.assertEqual(["item-1"], [item.id for item in retry.items])

    def test_set_item_note_retry_is_idempotent(self) -> None:
        self.create_order()
        self.add_coppa()
        command = SetItemNote(
            "cmd-note-once", "order-1", 1, "item-1", "Senza panna"
        )

        first = self.engine.set_item_note(command)
        retry = self.engine.set_item_note(command)

        self.assertEqual(first, retry)
        self.assertEqual(2, self.engine.get_order("order-1").version)
        self.assertEqual("Senza panna", retry.items[0].note)


if __name__ == "__main__":
    unittest.main()
