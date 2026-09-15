"""Thin Streamlit presentation for the in-memory Palmare demonstration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import streamlit as st

from hub_cavour.application.order_intake import OrderIntakeResult, ResolvedOrderPlan
from hub_cavour.application.palmare_order_service import (
    ConfirmResolvedOrder,
    PalmareConfirmationResult,
)
from hub_cavour.domain.money import Money
from hub_cavour.infrastructure.demo_runtime import (
    DEMO_PHRASE,
    DemoRuntime,
    build_demo_runtime,
)


_RUNTIME_KEY = "palmare_demo_runtime"
_PENDING_KEY = "palmare_demo_pending"
_RECEIPT_KEY = "palmare_demo_receipt"


@dataclass(frozen=True, slots=True)
class _PendingReview:
    source_text: str
    command_id: str
    expected_session_version: int
    result: OrderIntakeResult


def render_palmare_demo() -> None:
    runtime = _runtime()
    st.header("📱 Palmare Demo — Order Intake")
    st.caption(
        "Demo locale e deterministica: nessuna AI, voce, cassa o integrazione POS."
    )
    session = runtime.table_sessions.get_session(runtime.session_id)
    st.info(
        f"Sessione attiva: **Tavolo 7** — `{session.id}` — "
        f"versione `{session.version}`"
    )

    with st.form("palmare_intake_form"):
        text = st.text_area(
            "Comanda testuale",
            value=DEMO_PHRASE,
            height=110,
        )
        interpret = st.form_submit_button("Interpreta comanda")

    if interpret:
        result = runtime.intake.prepare(text)
        st.session_state[_PENDING_KEY] = _PendingReview(
            source_text=text,
            command_id=uuid4().hex,
            expected_session_version=session.version,
            result=result,
        )
        st.session_state.pop(_RECEIPT_KEY, None)

    pending: _PendingReview | None = st.session_state.get(_PENDING_KEY)
    if pending is None:
        st.write("Interpreta la comanda per visualizzare il piano strutturato.")
        return

    if not pending.result.ready or pending.result.plan is None:
        st.subheader("Richiesta di chiarimento")
        for issue in pending.result.issues:
            details = issue.message
            if issue.candidates:
                details += f" Candidati: {', '.join(issue.candidates)}."
            st.error(f"`{issue.code.value}` — {details}")
        st.warning("Nessun ordine è stato creato o modificato.")
        return

    plan = pending.result.plan
    st.subheader("Piano strutturato da revisionare")
    st.write(f"Tavolo risolto: `{plan.table_id}`")
    st.table(_review_rows(runtime, plan))
    st.caption("I prezzi non provengono dall’interprete e saranno applicati dall’Engine.")

    receipt: PalmareConfirmationResult | None = st.session_state.get(_RECEIPT_KEY)
    if receipt is None:
        if st.button("Conferma e invia", type="primary"):
            try:
                receipt = runtime.palmare.confirm(
                    ConfirmResolvedOrder(
                        command_id=pending.command_id,
                        session_id=runtime.session_id,
                        expected_session_version=pending.expected_session_version,
                        intake_result=pending.result,
                    )
                )
            except Exception as error:  # presentation boundary
                st.error(f"Invio non riuscito: {error}")
            else:
                st.session_state[_RECEIPT_KEY] = receipt

    if receipt is not None:
        st.success(
            f"Ordine `{receipt.order.id}` confermato e registrato come invio "
            f"n. {receipt.session.submissions[-1].sequence}."
        )
        st.table(_receipt_rows(receipt))
        st.metric("Totale determinato dall’Order Engine", _format_money(receipt.order.total))


def _runtime() -> DemoRuntime:
    runtime = st.session_state.get(_RUNTIME_KEY)
    if runtime is None:
        runtime = build_demo_runtime()
        st.session_state[_RUNTIME_KEY] = runtime
    return runtime


def _review_rows(runtime: DemoRuntime, plan: ResolvedOrderPlan) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in plan.items:
        product = runtime.catalog.get(item.product_id)
        modifiers_by_id = {modifier.id: modifier for modifier in product.modifiers}
        modifier_names = [
            modifiers_by_id[modifier.modifier_id].name
            for modifier in item.modifiers
        ]
        rows.append(
            {
                "Quantità": str(item.quantity),
                "Prodotto": product.name,
                "Modificatori": ", ".join(modifier_names) or "—",
                "Note": item.note or "—",
            }
        )
    return rows


def _receipt_rows(receipt: PalmareConfirmationResult) -> list[dict[str, str]]:
    return [
        {
            "Quantità": str(item.quantity),
            "Prodotto": item.product_name,
            "Modificatori": ", ".join(
                modifier.name for modifier in item.modifiers
            )
            or "—",
            "Totale": _format_money(item.total),
        }
        for item in receipt.order.items
    ]


def _format_money(value: Money) -> str:
    euros, cents = divmod(value.cents, 100)
    return f"€ {euros},{cents:02d}"
