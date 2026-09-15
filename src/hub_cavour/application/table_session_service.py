"""Application service coordinating tables, sessions and confirmed orders."""

from __future__ import annotations

from collections.abc import Callable

from hub_cavour.application.dining_commands import (
    AssignOrderToSession,
    CloseTableSession,
    OpenTableSession,
    SubmitOrderToSession,
)
from hub_cavour.application.dining_ports import (
    TableRepository,
    TableSessionRepository,
)
from hub_cavour.application.idempotency import command_fingerprint
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.domain.dining import (
    SubmittedModifierSnapshot,
    SubmittedOrderItemSnapshot,
    SubmittedOrderSnapshot,
    TableSession,
)
from hub_cavour.domain.errors import (
    InvalidOrderTransition,
    OrderNotConfirmed,
    VersionConflict,
)
from hub_cavour.domain.orders import Order, OrderStatus


class TableSessionService:
    def __init__(
        self,
        tables: TableRepository,
        sessions: TableSessionRepository,
        orders: OrderEngine,
    ) -> None:
        self._tables = tables
        self._sessions = sessions
        self._orders = orders

    def open_session(self, command: OpenTableSession) -> TableSession:
        def operation() -> TableSession:
            self._tables.get(command.table_id)
            return self._sessions.create(
                TableSession(id=command.session_id, table_id=command.table_id)
            )

        return self._execute(command, operation)

    def submit_order(self, command: SubmitOrderToSession) -> TableSession:
        def operation() -> TableSession:
            session = self._sessions.get_at_version(
                command.session_id, command.expected_session_version
            )
            order = self._orders.get_order(command.order_id)
            if order.version != command.expected_order_version:
                raise VersionConflict(command.expected_order_version, order.version)
            if order.status is not OrderStatus.CONFIRMED:
                raise OrderNotConfirmed(
                    f"Order {order.id!r} must be confirmed before submission"
                )
            session.add_submission(self._snapshot(order))
            return self._sessions.save(
                session, command.expected_session_version
            )

        return self._execute(command, operation)

    def assign_order(self, command: AssignOrderToSession) -> TableSession:
        def operation() -> TableSession:
            session = self._sessions.get_at_version(
                command.session_id, command.expected_session_version
            )
            order = self._orders.get_order(command.order_id)
            if order.status is not OrderStatus.DRAFT:
                raise InvalidOrderTransition(
                    f"Order {order.id!r} must be draft when assigned to a session"
                )
            session.assign_order(order.id)
            return self._sessions.save(
                session, command.expected_session_version
            )

        return self._execute(command, operation)

    def close_session(self, command: CloseTableSession) -> TableSession:
        def operation() -> TableSession:
            session = self._sessions.get_at_version(
                command.session_id, command.expected_session_version
            )
            session.close()
            return self._sessions.save(
                session, command.expected_session_version
            )

        return self._execute(command, operation)

    def get_session(self, session_id: str) -> TableSession:
        return self._sessions.get(session_id)

    def _execute(
        self,
        command: object,
        operation: Callable[[], TableSession],
    ) -> TableSession:
        command_id = getattr(command, "command_id")
        return self._sessions.execute_once(
            command_id,
            command_fingerprint(command),
            operation,
        )

    @staticmethod
    def _snapshot(order: Order) -> SubmittedOrderSnapshot:
        return SubmittedOrderSnapshot(
            order_id=order.id,
            order_version=order.version,
            currency=order.currency,
            items=tuple(
                SubmittedOrderItemSnapshot(
                    item_id=item.id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    base_unit_price=item.base_unit_price,
                    quantity=item.quantity,
                    modifiers=tuple(
                        SubmittedModifierSnapshot(
                            modifier_id=modifier.modifier_id,
                            name=modifier.name,
                            price_delta=modifier.price_delta,
                            quantity=modifier.quantity,
                        )
                        for modifier in item.modifiers
                    ),
                    note=item.note,
                )
                for item in order.items
            ),
        )
