"""In-memory composition root for the isolated Palmare Streamlit demo."""

from __future__ import annotations

from dataclasses import dataclass

from hub_cavour.application.dining_commands import OpenTableSession
from hub_cavour.application.order_engine import OrderEngine
from hub_cavour.application.order_intake import (
    InterpretationResult,
    OrderIntakeService,
    OrderIntentResolver,
    ParsedModifier,
    ParsedOrderIntent,
    ParsedOrderLine,
)
from hub_cavour.application.palmare_order_service import PalmareOrderService
from hub_cavour.application.table_session_service import TableSessionService
from hub_cavour.domain.catalog import (
    CatalogModifier,
    CatalogProduct,
    InMemoryCatalog,
)
from hub_cavour.domain.dining import Table
from hub_cavour.domain.money import Money
from hub_cavour.infrastructure.deterministic_order_interpreter import (
    DeterministicOrderInterpreter,
)
from hub_cavour.infrastructure.in_memory_repository import InMemoryOrderRepository
from hub_cavour.infrastructure.in_memory_table_repository import (
    InMemoryTableRepository,
)
from hub_cavour.infrastructure.in_memory_table_session_repository import (
    InMemoryTableSessionRepository,
)


DEMO_PHRASE = (
    "tavolo 7, due cappuccini, uno senza lattosio, "
    "un waffle con Nutella e banana"
)
DEMO_SESSION_ID = "demo-session-table-7"


@dataclass(slots=True)
class DemoRuntime:
    catalog: InMemoryCatalog
    tables: InMemoryTableRepository
    orders: InMemoryOrderRepository
    sessions: InMemoryTableSessionRepository
    order_engine: OrderEngine
    table_sessions: TableSessionService
    intake: OrderIntakeService
    palmare: PalmareOrderService
    session_id: str


def build_demo_runtime() -> DemoRuntime:
    catalog = InMemoryCatalog(
        (
            CatalogProduct(
                "prod-cappuccino",
                "Cappuccino",
                Money(180),
                (
                    CatalogModifier(
                        "mod-lactose-free", "Senza lattosio", Money(50)
                    ),
                ),
            ),
            CatalogProduct(
                "prod-waffle",
                "Waffle",
                Money(600),
                (
                    CatalogModifier("mod-nutella", "Nutella", Money(100)),
                    CatalogModifier("mod-banana", "Banana", Money(80)),
                ),
            ),
        )
    )
    tables = InMemoryTableRepository((Table("table-7", "Tavolo 7"),))
    orders = InMemoryOrderRepository()
    sessions = InMemoryTableSessionRepository()
    order_engine = OrderEngine(catalog, orders)
    table_sessions = TableSessionService(tables, sessions, order_engine)
    table_sessions.open_session(
        OpenTableSession("demo:open-table-7", DEMO_SESSION_ID, "table-7")
    )

    intent = ParsedOrderIntent(
        source_text=DEMO_PHRASE,
        table_reference="Tavolo 7",
        lines=(
            ParsedOrderLine(1, "Cappuccino"),
            ParsedOrderLine(
                1,
                "Cappuccino",
                (ParsedModifier("Senza lattosio"),),
            ),
            ParsedOrderLine(
                1,
                "Waffle",
                (ParsedModifier("Nutella"), ParsedModifier("Banana")),
            ),
        ),
    )
    interpreter = DeterministicOrderInterpreter(
        {DEMO_PHRASE: InterpretationResult(intent=intent)}
    )
    intake = OrderIntakeService(
        interpreter,
        OrderIntentResolver(catalog, tables),
    )
    palmare = PalmareOrderService(order_engine, table_sessions)
    return DemoRuntime(
        catalog=catalog,
        tables=tables,
        orders=orders,
        sessions=sessions,
        order_engine=order_engine,
        table_sessions=table_sessions,
        intake=intake,
        palmare=palmare,
        session_id=DEMO_SESSION_ID,
    )
