"""Explicit errors raised by the order domain and its application service."""


class OrderEngineError(Exception):
    """Base class for expected Order Engine errors."""


class InvalidMoney(OrderEngineError):
    pass


class InvalidQuantity(OrderEngineError):
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
