"""Thread-safe in-memory persistence for table service sessions."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock

from hub_cavour.domain.dining import TableSession, TableSessionStatus
from hub_cavour.domain.errors import (
    IdempotencyConflict,
    InvalidTableSessionTransition,
    OrderAlreadyAssigned,
    TableAlreadyOccupied,
    TableSessionAlreadyExists,
    TableSessionNotFound,
    TableSessionVersionConflict,
)


@dataclass(slots=True)
class _ProcessedSessionCommand:
    fingerprint: str
    result: TableSession


class InMemoryTableSessionRepository:
    """Session store whose command-id scope is TableSessionService."""

    def __init__(self) -> None:
        self._sessions: dict[str, TableSession] = {}
        self._open_session_by_table: dict[str, str] = {}
        self._order_session_by_id: dict[str, str] = {}
        self._processed_commands: dict[str, _ProcessedSessionCommand] = {}
        self._lock = RLock()

    def execute_once(
        self,
        command_id: str,
        fingerprint: str,
        operation: Callable[[], TableSession],
    ) -> TableSession:
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
            self._processed_commands[command_id] = _ProcessedSessionCommand(
                fingerprint=fingerprint,
                result=snapshot,
            )
            return deepcopy(snapshot)

    def create(self, session: TableSession) -> TableSession:
        with self._lock:
            session.validate()
            if (
                session.status is not TableSessionStatus.OPEN
                or session.version != 0
                or session.assigned_order_ids
                or session.submissions
            ):
                raise InvalidTableSessionTransition(
                    "A new session must be open, empty and at version zero"
                )
            if session.id in self._sessions:
                raise TableSessionAlreadyExists(
                    f"Table session {session.id!r} already exists"
                )
            active_session = self._open_session_by_table.get(session.table_id)
            if active_session is not None:
                raise TableAlreadyOccupied(
                    f"Table {session.table_id!r} already has open session "
                    f"{active_session!r}"
                )
            self._sessions[session.id] = deepcopy(session)
            self._open_session_by_table[session.table_id] = session.id
            return deepcopy(session)

    def get(self, session_id: str) -> TableSession:
        with self._lock:
            try:
                return deepcopy(self._sessions[session_id])
            except KeyError as error:
                raise TableSessionNotFound(
                    f"Table session {session_id!r} was not found"
                ) from error

    def get_at_version(
        self, session_id: str, expected_version: int
    ) -> TableSession:
        with self._lock:
            session = self.get(session_id)
            if session.version != expected_version:
                raise TableSessionVersionConflict(expected_version, session.version)
            return session

    def save(self, session: TableSession, expected_version: int) -> TableSession:
        with self._lock:
            current = self.get(session.id)
            if current.version != expected_version:
                raise TableSessionVersionConflict(expected_version, current.version)
            session.validate()
            self._validate_persistence_transition(current, session)

            new_assignments = session.assigned_order_ids[
                len(current.assigned_order_ids) :
            ]
            for order_id in new_assignments:
                owner = self._order_session_by_id.get(order_id)
                if owner is not None and owner != session.id:
                    raise OrderAlreadyAssigned(
                        f"Order {order_id!r} is already assigned to session {owner!r}"
                    )

            saved = deepcopy(session)
            saved.version = expected_version + 1
            self._sessions[session.id] = saved
            self._order_session_by_id.update(
                (order_id, session.id) for order_id in new_assignments
            )

            if (
                current.status is TableSessionStatus.OPEN
                and saved.status is TableSessionStatus.CLOSED
            ):
                self._open_session_by_table.pop(saved.table_id, None)
            return deepcopy(saved)

    @staticmethod
    def _validate_persistence_transition(
        current: TableSession, candidate: TableSession
    ) -> None:
        if candidate.table_id != current.table_id:
            raise InvalidTableSessionTransition("A session cannot change table")
        if current.status is TableSessionStatus.CLOSED:
            raise InvalidTableSessionTransition("A closed session cannot be changed")
        if (
            candidate.assigned_order_ids[: len(current.assigned_order_ids)]
            != current.assigned_order_ids
        ):
            raise InvalidTableSessionTransition(
                "Previous order assignments cannot be changed or removed"
            )
        if candidate.submissions[: len(current.submissions)] != current.submissions:
            raise InvalidTableSessionTransition(
                "Previous order submissions cannot be changed or removed"
            )
        if len(candidate.assigned_order_ids) - len(current.assigned_order_ids) > 1:
            raise InvalidTableSessionTransition(
                "Only one order can be assigned per command"
            )
        if len(candidate.submissions) - len(current.submissions) > 1:
            raise InvalidTableSessionTransition(
                "Only one order submission can be added per command"
            )
