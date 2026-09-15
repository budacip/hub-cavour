"""Explicit errors raised by the order domain and its application service."""


class OrderEngineError(Exception):
    """Base class for expected Order Engine errors."""


class InvalidMoney(OrderEngineError):
    pass


class InvalidQuantity(OrderEngineError):
    pass


class InvalidModifierQuantity(OrderEngineError):
    pass


class InvalidNote(OrderEngineError):
    pass


class InvalidOrderTransition(OrderEngineError):
    pass


class EmptyOrder(OrderEngineError):
    pass


class ProductNotFound(OrderEngineError):
    pass


class ModifierNotAllowed(OrderEngineError):
    pass


class InvalidItemPrice(OrderEngineError):
    pass


class OrderNotFound(OrderEngineError):
    pass


class OrderAlreadyExists(OrderEngineError):
    pass


class ItemNotFound(OrderEngineError):
    pass


class VersionConflict(OrderEngineError):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Order version conflict: expected {expected}, actual {actual}"
        )


class IdempotencyConflict(OrderEngineError):
    pass


class TableNotFound(OrderEngineError):
    pass


class TableAlreadyOccupied(OrderEngineError):
    pass


class TableSessionNotFound(OrderEngineError):
    pass


class TableSessionAlreadyExists(OrderEngineError):
    pass


class TableSessionVersionConflict(OrderEngineError):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Table session version conflict: expected {expected}, actual {actual}"
        )


class InvalidTableSessionTransition(OrderEngineError):
    pass


class OrderNotConfirmed(OrderEngineError):
    pass


class OrderAlreadySubmitted(OrderEngineError):
    pass


class OrderNotAssignedToSession(OrderEngineError):
    pass


class OrderAlreadyAssigned(OrderEngineError):
    pass


class InvalidIdentifier(OrderEngineError):
    pass


class InvalidVersion(OrderEngineError):
    pass


class InvalidSubmissionSequence(OrderEngineError):
    pass
