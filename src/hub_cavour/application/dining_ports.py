"""Persistence ports required by the dining-room application service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from hub_cavour.domain.dining import Table, TableSession


class TableRepository(Protocol):
    def get(self, table_id: str) -> Table:
        ...


class TableSessionRepository(Protocol):
    def execute_once(
        self,
        command_id: str,
        fingerprint: str,
        operation: Callable[[], TableSession],
    ) -> TableSession:
        ...

    def create(self, session: TableSession) -> TableSession:
        ...

    def get(self, session_id: str) -> TableSession:
        ...

    def get_at_version(
        self, session_id: str, expected_version: int
    ) -> TableSession:
        ...

    def save(self, session: TableSession, expected_version: int) -> TableSession:
        ...
