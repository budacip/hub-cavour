"""Apply a reviewed intake plan through the existing application services."""

from __future__ import annotations

from dataclasses import dataclass

from hub_cavour.application.commands import (
    AddItem,
    ConfirmOrder,
    CreateOrder,
    ModifierSelection,
    SetItemNote,
)
from hub_cavour.application.dining_commands import (
    AssignOrderToSession,
    SubmitOrderToSession,
)
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.application.order_intake import OrderIntakeResult
from hub_cavour.application.table_session_service import TableSessionService
from hub_cavour.domain.dining import TableSession
from hub_cavour.domain.errors import (
    InvalidIdentifier,
    InvalidVersion,
    OrderNotFound,
    TableSessionVersionConflict,
)
from hub_cavour.domain.orders import Order


class UnresolvedOrderIntake(Exception):
    pass


class PlanTableMismatch(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ConfirmResolvedOrder:
    command_id: str
    session_id: str
    expected_session_version: int
    intake_result: OrderIntakeResult

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise InvalidIdentifier("Command id must be a non-empty string")
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise InvalidIdentifier("Table session id must be a non-empty string")
        if (
            type(self.expected_session_version) is not int
            or self.expected_session_version < 0
        ):
            raise InvalidVersion(
                "Expected session version must be a non-negative integer"
            )


@dataclass(frozen=True, slots=True)
class PalmareConfirmationResult:
    order: Order
    session: TableSession


class PalmareOrderService:
    """Confirm and apply one fully resolved plan; interpretation lives elsewhere."""

    def __init__(
        self,
        orders: OrderEngine,
        table_sessions: TableSessionService,
    ) -> None:
        self._orders = orders
        self._table_sessions = table_sessions

    def confirm(self, command: ConfirmResolvedOrder) -> PalmareConfirmationResult:
        if not command.intake_result.ready or command.intake_result.plan is None:
            raise UnresolvedOrderIntake(
                "An intake result with clarification issues cannot be applied"
            )
        plan = command.intake_result.plan
        order_id = f"palmare-order:{command.command_id}"

        # Validate the destination before the first mutation. On retry the derived
        # order already exists and the underlying idempotent commands resume safely.
        if not self._order_exists(order_id):
            session = self._table_sessions.get_session(command.session_id)
            if session.version != command.expected_session_version:
                raise TableSessionVersionConflict(
                    command.expected_session_version, session.version
                )
            if session.table_id != plan.table_id:
                raise PlanTableMismatch(
                    f"Plan table {plan.table_id!r} does not match session table "
                    f"{session.table_id!r}"
                )

        order = self._orders.create_order(
            CreateOrder(f"{command.command_id}:create", order_id)
        )
        assigned = self._table_sessions.assign_order(
            AssignOrderToSession(
                f"{command.command_id}:assign",
                command.session_id,
                command.expected_session_version,
                order.id,
            )
        )

        for index, planned_item in enumerate(plan.items, start=1):
            item_id = f"{order.id}:item:{index}"
            order = self._orders.add_item(
                AddItem(
                    command_id=f"{command.command_id}:add:{index}",
                    order_id=order.id,
                    expected_version=order.version,
                    item_id=item_id,
                    product_id=planned_item.product_id,
                    quantity=planned_item.quantity,
                    modifier_selections=tuple(
                        ModifierSelection(modifier.modifier_id, modifier.quantity)
                        for modifier in planned_item.modifiers
                    ),
                )
            )
            if planned_item.note:
                order = self._orders.set_item_note(
                    SetItemNote(
                        command_id=f"{command.command_id}:note:{index}",
                        order_id=order.id,
                        expected_version=order.version,
                        item_id=item_id,
                        note=planned_item.note,
                    )
                )

        order = self._orders.confirm_order(
            ConfirmOrder(
                f"{command.command_id}:confirm",
                order.id,
                order.version,
            )
        )
        session = self._table_sessions.submit_order(
            SubmitOrderToSession(
                f"{command.command_id}:submit",
                command.session_id,
                assigned.version,
                order.id,
                order.version,
            )
        )
        return PalmareConfirmationResult(order=order, session=session)

    def _order_exists(self, order_id: str) -> bool:
        try:
            self._orders.get_order(order_id)
        except OrderNotFound:
            return False
        return True
