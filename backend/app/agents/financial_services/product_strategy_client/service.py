"""Wire the Product/Strategy/Client orchestrators into the job system."""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.product_strategy_client.orchestrator import (
    ProductCommercialOrchestrator,
    ProductInitiativeOrchestrator,
)
from app.agents.financial_services.product_strategy_client.schemas import (
    CommercialRequest,
    InitiativeRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_INITIATIVE = "product.initiative"
JOB_KIND_COMMERCIAL = "product.commercial"


def _forward(job_id: str, emit: Emit):  # type: ignore[no-untyped-def]
    """Adapt subagent :class:`StepEvent`s into job progress events."""

    async def step_emit(event: StepEvent) -> None:
        await emit(
            ProgressEvent(
                job_id=job_id,
                type="step",
                payload={"step": event.step, "status": event.status.value},
            )
        )

    return step_emit


def make_initiative_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the discovery->pricing->filing-gate->launch job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = InitiativeRequest.model_validate(job.payload)
        orchestrator = ProductInitiativeOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_commercial_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the parallel commercial-loop job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = CommercialRequest.model_validate(job.payload)
        orchestrator = ProductCommercialOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Product job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_INITIATIVE, make_initiative_handler(ctx))
    ctx.jobs.register(JOB_KIND_COMMERCIAL, make_commercial_handler(ctx))
