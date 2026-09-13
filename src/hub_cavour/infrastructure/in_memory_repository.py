"""Thread-safe in-memory repository with atomic idempotency handling."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from hub_cavour.domain.errors import (
    IdempotencyConflict,
    OrderAlreadyExists,
    OrderNotFound,
    VersionConflict,
)
from hub_cavour.domain.orders import Order


@dataclass(slots=True)
class _ProcessedCommand:
    fingerprint: str
    result: Order


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._processed_commands: dict[str, _ProcessedCommand] = {}
        self._lock = RLock()

    def execute_once(
        self,
        command_id: str,
        fingerprint: str,
        operation: Callable[[], Order],
    ) -> Order:
        with self._lock:
            processed = self._processed_commands.get(command_id)
            if processed is not None:
                if processed.fingerprint != fingerprint:
                    raise IdempotencyConflict(
                        f"Command id {command_id!r} was reused with a different payload"
                    )
                return deepcopy(processed.result)

            result = operation()
            snapshot = deepcopy(result)
            self._processed_commands[command_id] = _ProcessedCommand(
                fingerprint=fingerprint,
                result=snapshot,
            )
            return deepcopy(snapshot)

    def create(self, order: Order) -> Order:
        with self._lock:
            if order.id in self._orders:
                raise OrderAlreadyExists(f"Order {order.id!r} already exists")
            self._orders[order.id] = deepcopy(order)
            return deepcopy(order)

    def get(self, order_id: str) -> Order:
        with self._lock:
            try:
                return deepcopy(self._orders[order_id])
            except KeyError as error:
                raise OrderNotFound(f"Order {order_id!r} was not found") from error

    def get_at_version(self, order_id: str, expected_version: int) -> Order:
        order = self.get(order_id)
        if order.version != expected_version:
            raise VersionConflict(expected_version, order.version)
        return order

    def save(self, order: Order, expected_version: int) -> Order:
        with self._lock:
            current = self.get(order.id)
            if current.version != expected_version:
                raise VersionConflict(expected_version, current.version)
            saved = deepcopy(order)
            saved.version = expected_version + 1
            self._orders[order.id] = saved
            return deepcopy(saved)
