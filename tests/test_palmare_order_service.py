from __future__ import annotations

from dataclasses import replace
import unittest

from hub_cavour.application.order_intake import OrderIntakeResult, ResolvedOrderPlan
from hub_cavour.application.palmare_order_service import (
    ConfirmResolvedOrder,
    PlanTableMismatch,
    UnresolvedOrderIntake,
)
from hub_cavour.domain.errors import (
    IdempotencyConflict,
    OrderNotFound,
    TableSessionVersionConflict,
)
from hub_cavour.domain.money import Money
from hub_cavour.infrastructure.demo_runtime import DEMO_PHRASE, build_demo_runtime


class PalmareOrderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = build_demo_runtime()
        self.intake_result = self.runtime.intake.prepare(DEMO_PHRASE)
        self.command = ConfirmResolvedOrder(
            command_id="demo-confirmation-1",
            session_id=self.runtime.session_id,
            expected_session_version=0,
            intake_result=self.intake_result,
        )

    def assert_order_does_not_exist(self, command_id: str) -> None:
        with self.assertRaises(OrderNotFound):
            self.runtime.order_engine.get_order(f"palmare-order:{command_id}")

    def test_preparing_review_does_not_mutate_order_or_session(self) -> None:
        self.assertTrue(self.intake_result.ready)
        self.assert_order_does_not_exist(self.command.command_id)
        session = self.runtime.table_sessions.get_session(self.runtime.session_id)
        self.assertEqual(0, session.version)
        self.assertEqual((), session.assigned_order_ids)
        self.assertEqual((), session.submissions)

    def test_unresolved_intake_is_rejected_before_any_mutation(self) -> None:
        unresolved = self.runtime.intake.prepare("testo non supportato")
        command = replace(
            self.command,
            command_id="unresolved-confirmation",
            intake_result=unresolved,
        )

        with self.assertRaises(UnresolvedOrderIntake):
            self.runtime.palmare.confirm(command)

        self.assert_order_does_not_exist(command.command_id)
        self.assertEqual(
            0,
            self.runtime.table_sessions.get_session(self.runtime.session_id).version,
        )

    def test_plan_for_another_table_is_rejected_before_order_creation(self) -> None:
        assert self.intake_result.plan is not None
        wrong_plan = replace(self.intake_result.plan, table_id="table-8")
        command = replace(
            self.command,
            command_id="wrong-table-confirmation",
            intake_result=OrderIntakeResult(plan=wrong_plan),
        )

        with self.assertRaises(PlanTableMismatch):
            self.runtime.palmare.confirm(command)

        self.assert_order_does_not_exist(command.command_id)

    def test_stale_session_version_is_rejected_before_order_creation(self) -> None:
        command = replace(
            self.command,
            command_id="stale-confirmation",
            expected_session_version=1,
        )

        with self.assertRaises(TableSessionVersionConflict):
            self.runtime.palmare.confirm(command)

        self.assert_order_does_not_exist(command.command_id)

    def test_confirm_applies_plan_and_submits_to_table_7(self) -> None:
        result = self.runtime.palmare.confirm(self.command)

        self.assertEqual("confirmed", result.order.status.value)
        self.assertEqual(3, len(result.order.items))
        self.assertEqual(Money(1190), result.order.total)
        self.assertEqual("table-7", result.session.table_id)
        self.assertEqual(2, result.session.version)
        self.assertEqual(1, len(result.session.submissions))
        self.assertEqual(result.order.id, result.session.submissions[0].order_id)
        self.assertEqual(Money(1190), result.session.submissions[0].order.total)
        self.assertEqual((), result.order.items[0].modifiers)
        self.assertEqual(
            ["mod-lactose-free"],
            [modifier.modifier_id for modifier in result.order.items[1].modifiers],
        )
        self.assertEqual(
            ["mod-nutella", "mod-banana"],
            [modifier.modifier_id for modifier in result.order.items[2].modifiers],
        )

    def test_exact_retry_is_idempotent(self) -> None:
        first = self.runtime.palmare.confirm(self.command)
        retry = self.runtime.palmare.confirm(self.command)

        self.assertEqual(first, retry)
        persisted = self.runtime.table_sessions.get_session(self.runtime.session_id)
        self.assertEqual(2, persisted.version)
        self.assertEqual(1, len(persisted.assigned_order_ids))
        self.assertEqual(1, len(persisted.submissions))

    def test_same_command_id_with_different_plan_is_rejected(self) -> None:
        self.runtime.palmare.confirm(self.command)
        assert self.intake_result.plan is not None
        changed_first_item = replace(self.intake_result.plan.items[0], quantity=2)
        changed_plan = ResolvedOrderPlan(
            table_id=self.intake_result.plan.table_id,
            items=(changed_first_item, *self.intake_result.plan.items[1:]),
        )
        changed_command = replace(
            self.command,
            intake_result=OrderIntakeResult(plan=changed_plan),
        )

        with self.assertRaises(IdempotencyConflict):
            self.runtime.palmare.confirm(changed_command)

        session = self.runtime.table_sessions.get_session(self.runtime.session_id)
        self.assertEqual(1, len(session.submissions))

    def test_demo_runtimes_do_not_share_in_memory_state(self) -> None:
        self.runtime.palmare.confirm(self.command)
        another_runtime = build_demo_runtime()

        self.assertEqual(
            0,
            another_runtime.table_sessions.get_session(
                another_runtime.session_id
            ).version,
        )
        with self.assertRaises(OrderNotFound):
            another_runtime.order_engine.get_order(
                f"palmare-order:{self.command.command_id}"
            )


if __name__ == "__main__":
    unittest.main()
