"""Natural-language-neutral intake contracts and authoritative resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from hub_cavour.application.dining_ports import TableRepository
from hub_cavour.domain.catalog import CatalogProduct


def normalize_reference(value: str) -> str:
    """Normalize for exact matching only; this deliberately is not fuzzy."""

    return " ".join(value.casefold().strip().split())


class ClarificationCode(StrEnum):
    UNSUPPORTED_INPUT = "unsupported_input"
    AMBIGUOUS_INPUT = "ambiguous_input"
    EMPTY_ORDER = "empty_order"
    UNKNOWN_TABLE = "unknown_table"
    AMBIGUOUS_TABLE = "ambiguous_table"
    UNKNOWN_PRODUCT = "unknown_product"
    AMBIGUOUS_PRODUCT = "ambiguous_product"
    UNKNOWN_MODIFIER = "unknown_modifier"
    AMBIGUOUS_MODIFIER = "ambiguous_modifier"
    DUPLICATE_MODIFIER = "duplicate_modifier"
    INVALID_QUANTITY = "invalid_quantity"
    INVALID_NOTE = "invalid_note"


@dataclass(frozen=True, slots=True)
class ClarificationIssue:
    code: ClarificationCode
    reference: str
    message: str
    line_index: int | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedModifier:
    reference: str
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class ParsedOrderLine:
    quantity: int
    product_reference: str
    modifiers: tuple[ParsedModifier, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class ParsedOrderIntent:
    source_text: str
    table_reference: str
    lines: tuple[ParsedOrderLine, ...]


@dataclass(frozen=True, slots=True)
class InterpretationResult:
    intent: ParsedOrderIntent | None
    issues: tuple[ClarificationIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return self.intent is not None and not self.issues


@dataclass(frozen=True, slots=True)
class ResolvedModifier:
    modifier_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class ResolvedOrderItem:
    product_id: str
    quantity: int
    modifiers: tuple[ResolvedModifier, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedOrderPlan:
    table_id: str
    items: tuple[ResolvedOrderItem, ...]


@dataclass(frozen=True, slots=True)
class OrderIntakeResult:
    plan: ResolvedOrderPlan | None
    issues: tuple[ClarificationIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return self.plan is not None and not self.issues


class OrderInterpreter(Protocol):
    def interpret(self, text: str) -> InterpretationResult:
        ...


class CatalogReader(Protocol):
    def list_all(self) -> tuple[CatalogProduct, ...]:
        ...


class OrderIntentResolver:
    """Resolve textual references using only authoritative local sources."""

    def __init__(self, catalog: CatalogReader, tables: TableRepository) -> None:
        self._catalog = catalog
        self._tables = tables

    def resolve(self, intent: ParsedOrderIntent) -> OrderIntakeResult:
        issues: list[ClarificationIssue] = []
        table_id = self._resolve_table(intent.table_reference, issues)
        resolved_items: list[ResolvedOrderItem] = []

        if not intent.lines:
            issues.append(
                ClarificationIssue(
                    ClarificationCode.EMPTY_ORDER,
                    "",
                    "The interpreted order contains no items",
                )
            )

        products = self._catalog.list_all()
        for line_index, line in enumerate(intent.lines):
            if type(line.quantity) is not int or line.quantity <= 0:
                issues.append(
                    ClarificationIssue(
                        ClarificationCode.INVALID_QUANTITY,
                        str(line.quantity),
                        "Item quantity must be a positive integer",
                        line_index,
                    )
                )
                continue
            if not isinstance(line.note, str):
                issues.append(
                    ClarificationIssue(
                        ClarificationCode.INVALID_NOTE,
                        repr(line.note),
                        "Item note must be text",
                        line_index,
                    )
                )
                continue

            product = self._resolve_product(
                line.product_reference, products, line_index, issues
            )
            if product is None:
                continue
            modifiers = self._resolve_modifiers(
                line.modifiers, product, line_index, issues
            )
            if modifiers is None:
                continue
            resolved_items.append(
                ResolvedOrderItem(
                    product_id=product.id,
                    quantity=line.quantity,
                    modifiers=modifiers,
                    note=line.note,
                )
            )

        if issues or table_id is None:
            return OrderIntakeResult(plan=None, issues=tuple(issues))
        return OrderIntakeResult(
            plan=ResolvedOrderPlan(table_id, tuple(resolved_items))
        )

    def _resolve_table(
        self, reference: str, issues: list[ClarificationIssue]
    ) -> str | None:
        normalized = normalize_reference(reference)
        matches = tuple(
            table
            for table in self._tables.list_all()
            if normalized in {
                normalize_reference(table.id),
                normalize_reference(table.name),
            }
        )
        if len(matches) == 1:
            return matches[0].id
        code = (
            ClarificationCode.UNKNOWN_TABLE
            if not matches
            else ClarificationCode.AMBIGUOUS_TABLE
        )
        issues.append(
            ClarificationIssue(
                code,
                reference,
                "Table reference could not be resolved uniquely",
                candidates=tuple(table.id for table in matches),
            )
        )
        return None

    @staticmethod
    def _resolve_product(
        reference: str,
        products: tuple[CatalogProduct, ...],
        line_index: int,
        issues: list[ClarificationIssue],
    ) -> CatalogProduct | None:
        normalized = normalize_reference(reference)
        matches = tuple(
            product
            for product in products
            if normalized in {
                normalize_reference(product.id),
                normalize_reference(product.name),
            }
        )
        if len(matches) == 1:
            return matches[0]
        code = (
            ClarificationCode.UNKNOWN_PRODUCT
            if not matches
            else ClarificationCode.AMBIGUOUS_PRODUCT
        )
        issues.append(
            ClarificationIssue(
                code,
                reference,
                "Product reference could not be resolved uniquely",
                line_index,
                tuple(product.id for product in matches),
            )
        )
        return None

    @staticmethod
    def _resolve_modifiers(
        parsed: tuple[ParsedModifier, ...],
        product: CatalogProduct,
        line_index: int,
        issues: list[ClarificationIssue],
    ) -> tuple[ResolvedModifier, ...] | None:
        resolved: list[ResolvedModifier] = []
        starting_issue_count = len(issues)
        seen_ids: set[str] = set()

        for requested in parsed:
            if type(requested.quantity) is not int or requested.quantity <= 0:
                issues.append(
                    ClarificationIssue(
                        ClarificationCode.INVALID_QUANTITY,
                        str(requested.quantity),
                        "Modifier quantity must be a positive integer",
                        line_index,
                    )
                )
                continue
            normalized = normalize_reference(requested.reference)
            matches = tuple(
                modifier
                for modifier in product.modifiers
                if normalized in {
                    normalize_reference(modifier.id),
                    normalize_reference(modifier.name),
                }
            )
            if len(matches) != 1:
                code = (
                    ClarificationCode.UNKNOWN_MODIFIER
                    if not matches
                    else ClarificationCode.AMBIGUOUS_MODIFIER
                )
                issues.append(
                    ClarificationIssue(
                        code,
                        requested.reference,
                        "Modifier reference could not be resolved uniquely for "
                        f"product {product.name!r}",
                        line_index,
                        tuple(modifier.id for modifier in matches),
                    )
                )
                continue
            modifier = matches[0]
            if modifier.id in seen_ids:
                issues.append(
                    ClarificationIssue(
                        ClarificationCode.DUPLICATE_MODIFIER,
                        requested.reference,
                        "The same modifier was interpreted more than once",
                        line_index,
                        (modifier.id,),
                    )
                )
                continue
            seen_ids.add(modifier.id)
            resolved.append(ResolvedModifier(modifier.id, requested.quantity))

        if len(issues) != starting_issue_count:
            return None
        return tuple(resolved)


class OrderIntakeService:
    """Interpret then resolve; this service never mutates an order."""

    def __init__(
        self, interpreter: OrderInterpreter, resolver: OrderIntentResolver
    ) -> None:
        self._interpreter = interpreter
        self._resolver = resolver

    def prepare(self, text: str) -> OrderIntakeResult:
        interpreted = self._interpreter.interpret(text)
        if not interpreted.ready:
            return OrderIntakeResult(plan=None, issues=interpreted.issues)
        assert interpreted.intent is not None
        return self._resolver.resolve(interpreted.intent)
