"""Server-side catalog types used to price order commands."""

from __future__ import annotations

from dataclasses import dataclass

from hub_cavour.domain.errors import InvalidItemPrice, ModifierNotAllowed, ProductNotFound
from hub_cavour.domain.money import Money


@dataclass(frozen=True, slots=True)
class CatalogModifier:
    id: str
    name: str
    price_delta: Money


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    id: str
    name: str
    price: Money
    modifiers: tuple[CatalogModifier, ...] = ()

    def __post_init__(self) -> None:
        if self.price.cents < 0:
            raise InvalidItemPrice("A catalog product cannot have a negative price")
        modifier_ids = [modifier.id for modifier in self.modifiers]
        if len(modifier_ids) != len(set(modifier_ids)):
            raise ModifierNotAllowed("Modifier ids must be unique within a product")
        for modifier in self.modifiers:
            if modifier.price_delta.currency != self.price.currency:
                raise InvalidItemPrice("Product and modifier currencies must match")

    def resolve_modifiers(
        self, modifier_ids: tuple[str, ...]
    ) -> tuple[CatalogModifier, ...]:
        if len(modifier_ids) != len(set(modifier_ids)):
            raise ModifierNotAllowed("The same modifier cannot be selected twice")
        available = {modifier.id: modifier for modifier in self.modifiers}
        try:
            return tuple(available[modifier_id] for modifier_id in modifier_ids)
        except KeyError as error:
            raise ModifierNotAllowed(
                f"Modifier {error.args[0]!r} is not allowed for product {self.id!r}"
            ) from error


class InMemoryCatalog:
    def __init__(self, products: tuple[CatalogProduct, ...] = ()) -> None:
        self._products = {product.id: product for product in products}

    def get(self, product_id: str) -> CatalogProduct:
        try:
            return self._products[product_id]
        except KeyError as error:
            raise ProductNotFound(f"Product {product_id!r} was not found") from error

    def put(self, product: CatalogProduct) -> None:
        self._products[product.id] = product
