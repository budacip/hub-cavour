"""Integer-based monetary value object: binary floating point is never used."""

from __future__ import annotations

from dataclasses import dataclass

from hub_cavour.domain.errors import InvalidMoney


@dataclass(frozen=True, slots=True)
class Money:
    cents: int
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if type(self.cents) is not int:
            raise InvalidMoney("Money must be expressed as an integer number of cents")
        if not self.currency or len(self.currency) != 3:
            raise InvalidMoney("Currency must be a three-letter ISO code")
        object.__setattr__(self, "currency", self.currency.upper())

    @classmethod
    def zero(cls, currency: str = "EUR") -> Money:
        return cls(0, currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise InvalidMoney(
                f"Cannot combine {self.currency} and {other.currency} amounts"
            )

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __mul__(self, quantity: int) -> Money:
        if type(quantity) is not int:
            raise InvalidMoney("Money can only be multiplied by an integer")
        return Money(self.cents * quantity, self.currency)

    __rmul__ = __mul__
