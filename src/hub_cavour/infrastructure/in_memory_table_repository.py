"""In-memory table catalog used by the dining-room application service."""

from __future__ import annotations

from hub_cavour.domain.dining import Table
from hub_cavour.domain.errors import TableNotFound


class InMemoryTableRepository:
    def __init__(self, tables: tuple[Table, ...] = ()) -> None:
        self._tables = {table.id: table for table in tables}

    def get(self, table_id: str) -> Table:
        try:
            return self._tables[table_id]
        except KeyError as error:
            raise TableNotFound(f"Table {table_id!r} was not found") from error
