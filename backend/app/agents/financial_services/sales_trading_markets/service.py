"""Wire the Sales & Trading / Markets orchestrator into the job system."""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.sales_trading_markets.orchestrator import (
    SalesTradingOrchestrator,
)
from app.agents.financial_services.sales_trading_markets.schemas import OrderRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_ORDER = "sales-trading-markets.order"


def _forward(job_id: str, emit: Emit):  # type: ignore[no-untyped-def]
    async def step_emit(event: StepEvent) -> None:
        await emit(
            ProgressEvent(
                job_id=job_id,
                type="step",
                payload={"step": event.step, "status": event.status.value},
            )
        )

    return step_emit


def make_order_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the order job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = OrderRequest.model_validate(job.payload)
        orchestrator = SalesTradingOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the order job handler on the shared queue."""
    ctx.jobs.register(JOB_KIND_ORDER, make_order_handler(ctx))
