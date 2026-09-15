from __future__ import annotations

import unittest

from hub_cavour.application.commands import (
    AddItem,
    ConfirmOrder,
    CreateOrder,
    ModifierSelection,
    SetItemNote,
)
from hub_cavour.application.dining_commands import (
    AssignOrderToSession,
    OpenTableSession,
    SubmitOrderToSession,
)
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.application.order_intake import (
    ClarificationCode,
    ClarificationIssue,
    InterpretationResult,
    OrderIntakeService,
    OrderIntentResolver,
    ParsedModifier,
    ParsedOrderIntent,
    ParsedOrderLine,
)
from hub_cavour.application.table_session_service import TableSessionService
from hub_cavour.domain.catalog import (
    CatalogModifier,
    CatalogProduct,
    InMemoryCatalog,
)
from hub_cavour.domain.dining import Table
from hub_cavour.domain.money import Money
from hub_cavour.infrastructure.deterministic_order_interpreter import (
    DeterministicOrderInterpreter,
)
from hub_cavour.infrastructure.in_memory_repository import InMemoryOrderRepository
from hub_cavour.infrastructure.in_memory_table_repository import (
    InMemoryTableRepository,
)
from hub_cavour.infrastructure.in_memory_table_session_repository import (
    InMemoryTableSessionRepository,
)


class OrderIntakeTests(unittest.TestCase):
    phrase = (
        "tavolo 7, due cappuccini, uno senza lattosio, "
        "un waffle con Nutella e banana"
    )

    def setUp(self) -> None:
        self.intent = ParsedOrderIntent(
            source_text=self.phrase,
            table_reference="Tavolo 7",
            lines=(
                ParsedOrderLine(quantity=1, product_reference="Cappuccino"),
                ParsedOrderLine(
                    quantity=1,
                    product_reference="Cappuccino",
                    modifiers=(ParsedModifier("Senza lattosio"),),
                ),
                ParsedOrderLine(
                    quantity=1,
                    product_reference="Waffle",
                    modifiers=(
                        ParsedModifier("Nutella"),
                        ParsedModifier("Banana"),
                    ),
                ),
            ),
        )
        self.catalog = InMemoryCatalog(
            (
                CatalogProduct(
                    "prod-cappuccino",
                    "Cappuccino",
                    Money(180),
                    (
                        CatalogModifier(
                            "mod-lactose-free", "Senza lattosio", Money(50)
                        ),
                    ),
                ),
                CatalogProduct(
                    "prod-waffle",
                    "Waffle",
                    Money(600),
                    (
                        CatalogModifier("mod-nutella", "Nutella", Money(100)),
                        CatalogModifier("mod-banana", "Banana", Money(80)),
                    ),
                ),
            )
        )
        self.tables = InMemoryTableRepository(
            (Table("table-7", "Tavolo 7"), Table("table-8", "Tavolo 8"))
        )
        self.interpreter = DeterministicOrderInterpreter(
            {self.phrase: InterpretationResult(intent=self.intent)}
        )
        self.intake = OrderIntakeService(
            self.interpreter,
            OrderIntentResolver(self.catalog, self.tables),
        )

    def test_deterministic_interpreter_splits_partial_modifier_scope(self) -> None:
        result = self.interpreter.interpret(self.phrase.upper())

        self.assertTrue(result.ready)
        assert result.intent is not None
        self.assertEqual([1, 1, 1], [line.quantity for line in result.intent.lines])
        self.assertEqual((), result.intent.lines[0].modifiers)
        self.assertEqual(
            (ParsedModifier("Senza lattosio"),), result.intent.lines[1].modifiers
        )
        self.assertEqual(
            (ParsedModifier("Nutella"), ParsedModifier("Banana")),
            result.intent.lines[2].modifiers,
        )
        self.assertFalse(hasattr(result.intent.lines[0], "product_id"))
        self.assertFalse(hasattr(result.intent.lines[0], "price"))

    def test_resolver_uses_only_authoritative_ids_and_no_prices(self) -> None:
        result = self.intake.prepare(self.phrase)

        self.assertTrue(result.ready)
        assert result.plan is not None
        self.assertEqual("table-7", result.plan.table_id)
        self.assertEqual(
            ["prod-cappuccino", "prod-cappuccino", "prod-waffle"],
            [item.product_id for item in result.plan.items],
        )
        self.assertEqual(
            [[], ["mod-lactose-free"], ["mod-nutella", "mod-banana"]],
            [
                [modifier.modifier_id for modifier in item.modifiers]
                for item in result.plan.items
            ],
        )
        catalog_ids = {product.id for product in self.catalog.list_all()}
        table_ids = {table.id for table in self.tables.list_all()}
        self.assertTrue(all(item.product_id in catalog_ids for item in result.plan.items))
        self.assertIn(result.plan.table_id, table_ids)
        self.assertTrue(all(not hasattr(item, "price") for item in result.plan.items))

    def test_phrase_reaches_order_engine_and_table_7_submission(self) -> None:
        result = self.intake.prepare(self.phrase)
        self.assertTrue(result.ready)
        assert result.plan is not None

        orders = InMemoryOrderRepository()
        engine = OrderEngine(self.catalog, orders)
        sessions = InMemoryTableSessionRepository()
        table_service = TableSessionService(self.tables, sessions, engine)
        opened = table_service.open_session(
            OpenTableSession("open-7", "session-7", result.plan.table_id)
        )
        order = engine.create_order(CreateOrder("create-order", "order-7-1"))
        assigned = table_service.assign_order(
            AssignOrderToSession(
                "assign-order", "session-7", opened.version, order.id
            )
        )

        for index, planned_item in enumerate(result.plan.items, start=1):
            order = engine.add_item(
                AddItem(
                    command_id=f"add-{index}",
                    order_id=order.id,
                    expected_version=order.version,
                    item_id=f"item-{index}",
                    product_id=planned_item.product_id,
                    quantity=planned_item.quantity,
                    modifier_selections=tuple(
                        ModifierSelection(modifier.modifier_id, modifier.quantity)
                        for modifier in planned_item.modifiers
                    ),
                )
            )
            if planned_item.note:
                order = engine.set_item_note(
                    SetItemNote(
                        f"note-{index}",
                        order.id,
                        order.version,
                        f"item-{index}",
                        planned_item.note,
                    )
                )

        self.assertEqual(Money(1190), order.total)
        confirmed = engine.confirm_order(
            ConfirmOrder("confirm-order", order.id, order.version)
        )
        session = table_service.submit_order(
            SubmitOrderToSession(
                "submit-order",
                "session-7",
                assigned.version,
                confirmed.id,
                confirmed.version,
            )
        )

        self.assertEqual("table-7", session.table_id)
        submitted_items = session.submissions[0].order.items
        self.assertEqual(3, len(submitted_items))
        self.assertEqual((), submitted_items[0].modifiers)
        self.assertEqual(
            ["mod-lactose-free"],
            [modifier.modifier_id for modifier in submitted_items[1].modifiers],
        )
        self.assertEqual(
            ["mod-nutella", "mod-banana"],
            [modifier.modifier_id for modifier in submitted_items[2].modifiers],
        )
        self.assertEqual(Money(1190), session.submissions[0].order.total)

    def test_unknown_references_return_issues_without_mutating_order(self) -> None:
        orders = InMemoryOrderRepository()
        engine = OrderEngine(self.catalog, orders)
        before = engine.create_order(CreateOrder("existing:create", "existing"))
        cases = (
            (
                "unknown product",
                ParsedOrderIntent(
                    "unknown product",
                    "Tavolo 7",
                    (ParsedOrderLine(1, "Capuccino"),),
                ),
                ClarificationCode.UNKNOWN_PRODUCT,
            ),
            (
                "unknown modifier",
                ParsedOrderIntent(
                    "unknown modifier",
                    "Tavolo 7",
                    (
                        ParsedOrderLine(
                            1,
                            "Cappuccino",
                            (ParsedModifier("Caramello"),),
                        ),
                    ),
                ),
                ClarificationCode.UNKNOWN_MODIFIER,
            ),
            (
                "unknown table",
                ParsedOrderIntent(
                    "unknown table",
                    "Tavolo 70",
                    (ParsedOrderLine(1, "Cappuccino"),),
                ),
                ClarificationCode.UNKNOWN_TABLE,
            ),
        )

        for text, intent, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                intake = OrderIntakeService(
                    DeterministicOrderInterpreter(
                        {text: InterpretationResult(intent=intent)}
                    ),
                    OrderIntentResolver(self.catalog, self.tables),
                )
                result = intake.prepare(text)
                self.assertFalse(result.ready)
                self.assertIsNone(result.plan)
                self.assertIn(expected_code, {issue.code for issue in result.issues})

        after = engine.get_order("existing")
        self.assertEqual(before, after)
        self.assertEqual(0, after.version)
        self.assertEqual([], after.items)

    def test_ambiguous_product_requires_clarification(self) -> None:
        ambiguous_catalog = InMemoryCatalog(
            (
                CatalogProduct("coffee-1", "Cappuccino", Money(180)),
                CatalogProduct("coffee-2", "Cappuccino", Money(200)),
            )
        )
        result = OrderIntakeService(
            self.interpreter,
            OrderIntentResolver(ambiguous_catalog, self.tables),
        ).prepare(self.phrase)

        self.assertFalse(result.ready)
        self.assertIsNone(result.plan)
        issue = next(
            issue
            for issue in result.issues
            if issue.code is ClarificationCode.AMBIGUOUS_PRODUCT
        )
        self.assertEqual(("coffee-1", "coffee-2"), issue.candidates)

    def test_interpreter_ambiguity_and_unsupported_input_do_not_resolve(self) -> None:
        ambiguous_text = "due cappuccini senza lattosio"
        ambiguity = ClarificationIssue(
            ClarificationCode.AMBIGUOUS_INPUT,
            "senza lattosio",
            "Specify how many cappuccini are lactose-free",
        )
        intake = OrderIntakeService(
            DeterministicOrderInterpreter(
                {ambiguous_text: InterpretationResult(None, (ambiguity,))}
            ),
            OrderIntentResolver(self.catalog, self.tables),
        )

        ambiguous = intake.prepare(ambiguous_text)
        unsupported = intake.prepare("un testo quasi uguale")

        self.assertEqual((ambiguity,), ambiguous.issues)
        self.assertIsNone(ambiguous.plan)
        self.assertEqual(
            ClarificationCode.UNSUPPORTED_INPUT, unsupported.issues[0].code
        )
        self.assertIsNone(unsupported.plan)


if __name__ == "__main__":
    unittest.main()
