from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from hub_cavour.application.commands import (
    AddItem,
    ChangeQuantity,
    ConfirmOrder,
    CreateOrder,
    ModifierSelection,
    SetItemNote,
)
from hub_cavour.application.dining_commands import (
    AssignOrderToSession,
    CloseTableSession,
    OpenTableSession,
    SubmitOrderToSession,
)
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.application.table_session_service import TableSessionService
from hub_cavour.domain.catalog import (
    CatalogModifier,
    CatalogProduct,
    InMemoryCatalog,
)
from hub_cavour.domain.dining import Table, TableSession, TableSessionStatus
from hub_cavour.domain.errors import (
    IdempotencyConflict,
    InvalidIdentifier,
    InvalidSubmissionSequence,
    InvalidTableSessionTransition,
    InvalidVersion,
    OrderAlreadyAssigned,
    OrderAlreadySubmitted,
    OrderNotAssignedToSession,
    OrderNotConfirmed,
    TableAlreadyOccupied,
    TableNotFound,
    TableSessionVersionConflict,
)
from hub_cavour.domain.money import Money
from hub_cavour.infrastructure.in_memory_repository import InMemoryOrderRepository
from hub_cavour.infrastructure.in_memory_table_repository import (
    InMemoryTableRepository,
)
from hub_cavour.infrastructure.in_memory_table_session_repository import (
    InMemoryTableSessionRepository,
)


class TableSessionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = InMemoryCatalog(
            (
                CatalogProduct(
                    "cappuccino",
                    "Cappuccino",
                    Money(180),
                    (CatalogModifier("lactose-free", "Senza lattosio", Money(50)),),
                ),
                CatalogProduct("waffle", "Waffle", Money(600)),
            )
        )
        self.order_repository = InMemoryOrderRepository()
        self.order_engine = OrderEngine(self.catalog, self.order_repository)
        self.session_repository = InMemoryTableSessionRepository()
        self.service = TableSessionService(
            tables=InMemoryTableRepository(
                (Table("table-7", "Tavolo 7"), Table("table-8", "Tavolo 8"))
            ),
            sessions=self.session_repository,
            orders=self.order_engine,
        )

    def open_session(
        self,
        session_id: str = "session-7-a",
        table_id: str = "table-7",
        command_id: str = "session-open",
    ):
        return self.service.open_session(
            OpenTableSession(command_id, session_id, table_id)
        )

    def create_draft_order(
        self,
        order_id: str,
        product_id: str,
        quantity: int = 1,
        modifier_selections: tuple[ModifierSelection, ...] = (),
        note: str = "",
    ):
        self.order_engine.create_order(CreateOrder(f"{order_id}:create", order_id))
        order = self.order_engine.add_item(
            AddItem(
                command_id=f"{order_id}:add",
                order_id=order_id,
                expected_version=0,
                item_id=f"{order_id}:item-1",
                product_id=product_id,
                quantity=quantity,
                modifier_selections=modifier_selections,
            )
        )
        if note:
            order = self.order_engine.set_item_note(
                SetItemNote(
                    f"{order_id}:note",
                    order_id,
                    order.version,
                    f"{order_id}:item-1",
                    note,
                )
            )
        return order

    def assign_order(
        self,
        order_id: str,
        session_version: int,
        session_id: str = "session-7-a",
        command_id: str | None = None,
    ):
        return self.service.assign_order(
            AssignOrderToSession(
                command_id or f"{order_id}:assign",
                session_id,
                session_version,
                order_id,
            )
        )

    def confirm_order(self, order_id: str, version: int):
        return self.order_engine.confirm_order(
            ConfirmOrder(f"{order_id}:confirm", order_id, version)
        )

    def test_open_session_on_table(self) -> None:
        session = self.open_session()

        self.assertEqual("session-7-a", session.id)
        self.assertEqual("table-7", session.table_id)
        self.assertEqual(TableSessionStatus.OPEN, session.status)
        self.assertEqual(0, session.version)
        self.assertEqual((), session.assigned_order_ids)
        self.assertEqual((), session.submissions)

    def test_unknown_table_is_rejected(self) -> None:
        with self.assertRaises(TableNotFound):
            self.open_session(table_id="missing")

    def test_cannot_open_two_sessions_on_same_table(self) -> None:
        self.open_session()

        with self.assertRaises(TableAlreadyOccupied):
            self.open_session("session-7-b", "table-7", "session-open-2")

    def test_successive_orders_preserve_submission_history(self) -> None:
        self.open_session()
        first_draft = self.create_draft_order("order-cappuccini", "cappuccino", 2)
        assigned = self.assign_order(first_draft.id, 0)
        first_order = self.confirm_order(first_draft.id, first_draft.version)
        first_result = self.service.submit_order(
            SubmitOrderToSession(
                "submit-cappuccini",
                "session-7-a",
                assigned.version,
                first_order.id,
                first_order.version,
            )
        )
        first_history_entry = first_result.submissions[0]

        second_draft = self.create_draft_order("order-waffle", "waffle")
        assigned = self.assign_order(second_draft.id, first_result.version)
        second_order = self.confirm_order(second_draft.id, second_draft.version)
        second_result = self.service.submit_order(
            SubmitOrderToSession(
                "submit-waffle",
                "session-7-a",
                assigned.version,
                second_order.id,
                second_order.version,
            )
        )

        self.assertEqual(4, second_result.version)
        self.assertEqual(first_history_entry, second_result.submissions[0])
        self.assertEqual(
            ["order-cappuccini", "order-waffle"],
            [submission.order_id for submission in second_result.submissions],
        )
        self.assertEqual([1, 2], [item.sequence for item in second_result.submissions])

    def test_draft_remains_editable_before_submission(self) -> None:
        self.open_session()
        draft = self.create_draft_order("order-1", "cappuccino")
        assigned = self.assign_order(draft.id, 0)
        edited = self.order_engine.change_quantity(
            ChangeQuantity("order:quantity", draft.id, draft.version, "order-1:item-1", 2)
        )
        confirmed = self.confirm_order(draft.id, edited.version)

        session = self.service.submit_order(
            SubmitOrderToSession(
                "order:submit",
                "session-7-a",
                assigned.version,
                confirmed.id,
                confirmed.version,
            )
        )

        self.assertEqual(2, session.submissions[0].order.items[0].quantity)

    def test_draft_order_cannot_be_submitted(self) -> None:
        self.open_session()
        draft = self.create_draft_order("draft-order", "cappuccino")
        assigned = self.assign_order(draft.id, 0)

        with self.assertRaises(OrderNotConfirmed):
            self.service.submit_order(
                SubmitOrderToSession(
                    "draft:submit",
                    "session-7-a",
                    assigned.version,
                    draft.id,
                    draft.version,
                )
            )
        self.assertEqual(assigned.version, self.service.get_session("session-7-a").version)

    def test_session_commands_are_idempotent_in_service_scope(self) -> None:
        open_command = OpenTableSession("open-once", "session-7-a", "table-7")
        self.assertEqual(
            self.service.open_session(open_command),
            self.service.open_session(open_command),
        )
        draft = self.create_draft_order("order-1", "cappuccino")
        assign_command = AssignOrderToSession("assign-once", "session-7-a", 0, draft.id)
        assigned = self.service.assign_order(assign_command)
        self.assertEqual(assigned, self.service.assign_order(assign_command))
        order = self.confirm_order(draft.id, draft.version)
        submit_command = SubmitOrderToSession(
            "submit-once", "session-7-a", assigned.version, order.id, order.version
        )
        submitted = self.service.submit_order(submit_command)
        self.assertEqual(submitted, self.service.submit_order(submit_command))
        close_command = CloseTableSession(
            "close-once", "session-7-a", submitted.version
        )
        closed = self.service.close_session(close_command)
        self.assertEqual(closed, self.service.close_session(close_command))

    def test_reused_command_id_and_stale_version_are_rejected(self) -> None:
        self.open_session(command_id="shared-command")
        with self.assertRaises(IdempotencyConflict):
            self.service.close_session(
                CloseTableSession("shared-command", "session-7-a", 0)
            )
        with self.assertRaises(TableSessionVersionConflict):
            self.service.close_session(CloseTableSession("stale", "session-7-a", 1))

    def test_order_cannot_be_submitted_twice(self) -> None:
        self.open_session()
        draft = self.create_draft_order("order-1", "cappuccino")
        assigned = self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)
        submitted = self.service.submit_order(
            SubmitOrderToSession(
                "submit-first",
                "session-7-a",
                assigned.version,
                order.id,
                order.version,
            )
        )

        with self.assertRaises(OrderAlreadySubmitted):
            self.service.submit_order(
                SubmitOrderToSession(
                    "submit-again",
                    "session-7-a",
                    submitted.version,
                    order.id,
                    order.version,
                )
            )

    def test_order_cannot_be_submitted_through_wrong_session(self) -> None:
        self.open_session()
        self.open_session("session-8-a", "table-8", "open-8")
        draft = self.create_draft_order("order-1", "cappuccino")
        self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)

        with self.assertRaises(OrderNotAssignedToSession):
            self.service.submit_order(
                SubmitOrderToSession(
                    "wrong-submit", "session-8-a", 0, order.id, order.version
                )
            )

    def test_order_cannot_be_assigned_to_two_sessions(self) -> None:
        self.open_session()
        self.open_session("session-8-a", "table-8", "open-8")
        draft = self.create_draft_order("order-1", "cappuccino")
        self.assign_order(draft.id, 0)

        with self.assertRaises(OrderAlreadyAssigned):
            self.assign_order(draft.id, 0, "session-8-a", "assign-to-8")

    def test_submission_is_an_exact_immutable_snapshot(self) -> None:
        self.open_session()
        draft = self.create_draft_order(
            "order-1",
            "cappuccino",
            quantity=2,
            modifier_selections=(ModifierSelection("lactose-free", 1),),
            note="Ben caldo",
        )
        assigned = self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)
        session = self.service.submit_order(
            SubmitOrderToSession(
                "submit", "session-7-a", assigned.version, order.id, order.version
            )
        )
        snapshot = session.submissions[0].order

        persisted = self.order_repository.get(order.id)
        persisted.items[0].set_quantity(99)
        self.order_repository.save(persisted, persisted.version)
        self.catalog.put(CatalogProduct("cappuccino", "Changed", Money(999)))

        self.assertEqual(order.id, snapshot.order_id)
        self.assertEqual(order.version, snapshot.order_version)
        self.assertEqual("EUR", snapshot.currency)
        self.assertEqual(2, snapshot.items[0].quantity)
        self.assertEqual(Money(180), snapshot.items[0].base_unit_price)
        self.assertEqual("Ben caldo", snapshot.items[0].note)
        self.assertEqual("lactose-free", snapshot.items[0].modifiers[0].modifier_id)
        self.assertEqual(Money(50), snapshot.items[0].modifiers[0].price_delta)
        self.assertEqual(Money(230), snapshot.items[0].unit_price)
        self.assertEqual(Money(460), snapshot.items[0].total)
        self.assertEqual(Money(460), snapshot.total)
        with self.assertRaises(FrozenInstanceError):
            snapshot.items[0].quantity = 3  # type: ignore[misc]

    def test_close_preserves_history_and_blocks_new_work(self) -> None:
        self.open_session()
        draft = self.create_draft_order("order-1", "waffle")
        assigned = self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)
        submitted = self.service.submit_order(
            SubmitOrderToSession(
                "submit", "session-7-a", assigned.version, order.id, order.version
            )
        )
        closed = self.service.close_session(
            CloseTableSession("close", "session-7-a", submitted.version)
        )

        self.assertEqual(submitted.submissions, closed.submissions)
        late_draft = self.create_draft_order("late-order", "waffle")
        with self.assertRaises(InvalidTableSessionTransition):
            self.assign_order(late_draft.id, closed.version)
        next_session = self.open_session("session-7-b", "table-7", "next-open")
        self.assertEqual(TableSessionStatus.OPEN, next_session.status)

    def test_previous_history_cannot_be_rewritten(self) -> None:
        self.open_session()
        draft = self.create_draft_order("order-1", "cappuccino")
        assigned = self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)
        submitted = self.service.submit_order(
            SubmitOrderToSession(
                "submit", "session-7-a", assigned.version, order.id, order.version
            )
        )
        submitted.submissions = ()

        with self.assertRaises(InvalidTableSessionTransition):
            self.session_repository.save(submitted, submitted.version)

    def test_empty_identifiers_are_rejected(self) -> None:
        with self.assertRaises(InvalidIdentifier):
            Table("", "Tavolo")
        with self.assertRaises(InvalidIdentifier):
            TableSession("session", " ")
        with self.assertRaises(InvalidIdentifier):
            OpenTableSession("command", "", "table-7")
        with self.assertRaises(InvalidIdentifier):
            AssignOrderToSession("command", "session", 0, "")

    def test_negative_versions_are_rejected(self) -> None:
        with self.assertRaises(InvalidVersion):
            TableSession("session", "table-7", version=-1)
        with self.assertRaises(InvalidVersion):
            SubmitOrderToSession("command", "session", -1, "order", 0)
        with self.assertRaises(InvalidVersion):
            SubmitOrderToSession("command", "session", 0, "order", -1)

    def test_incoherent_submission_sequence_is_rejected(self) -> None:
        self.open_session()
        draft = self.create_draft_order("order-1", "cappuccino")
        assigned = self.assign_order(draft.id, 0)
        order = self.confirm_order(draft.id, draft.version)
        submitted = self.service.submit_order(
            SubmitOrderToSession(
                "submit", "session-7-a", assigned.version, order.id, order.version
            )
        )
        incoherent = replace(submitted.submissions[0], sequence=2)

        with self.assertRaises(InvalidSubmissionSequence):
            TableSession(
                "invalid",
                "table-7",
                assigned_order_ids=(order.id,),
                submissions=(incoherent,),
            )


if __name__ == "__main__":
    unittest.main()
