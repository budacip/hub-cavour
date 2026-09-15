"""Immutable commands for table service sessions."""

from dataclasses import dataclass

from hub_cavour.domain.errors import InvalidIdentifier, InvalidVersion


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIdentifier(f"{label} must be a non-empty string")


def _require_version(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise InvalidVersion(f"{label} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class OpenTableSession:
    command_id: str
    session_id: str
    table_id: str

    def __post_init__(self) -> None:
        _require_id(self.command_id, "Command id")
        _require_id(self.session_id, "Table session id")
        _require_id(self.table_id, "Table id")


@dataclass(frozen=True, slots=True)
class AssignOrderToSession:
    command_id: str
    session_id: str
    expected_session_version: int
    order_id: str

    def __post_init__(self) -> None:
        _require_id(self.command_id, "Command id")
        _require_id(self.session_id, "Table session id")
        _require_version(self.expected_session_version, "Expected session version")
        _require_id(self.order_id, "Order id")


@dataclass(frozen=True, slots=True)
class SubmitOrderToSession:
    command_id: str
    session_id: str
    expected_session_version: int
    order_id: str
    expected_order_version: int

    def __post_init__(self) -> None:
        _require_id(self.command_id, "Command id")
        _require_id(self.session_id, "Table session id")
        _require_version(self.expected_session_version, "Expected session version")
        _require_id(self.order_id, "Order id")
        _require_version(self.expected_order_version, "Expected order version")


@dataclass(frozen=True, slots=True)
class CloseTableSession:
    command_id: str
    session_id: str
    expected_session_version: int

    def __post_init__(self) -> None:
        _require_id(self.command_id, "Command id")
        _require_id(self.session_id, "Table session id")
        _require_version(self.expected_session_version, "Expected session version")
