"""Wire the Corp Dev & Strategy orchestrators into the job system.

Two job kinds — the hybrid deal run and the parallel standing/IR run — each run
their orchestrator in a worker and forward every subagent lifecycle event onto the
job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.corpdev.orchestrator import (
    CorpDevDealOrchestrator,
    CorpDevStandingOrchestrator,
)
from app.agents.enterprise.corpdev.schemas import DealRequest, EarningsPackRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_DEAL = "corpdev.deal"
JOB_KIND_EARNINGS = "corpdev.earnings"


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


def make_deal_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the deal job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = DealRequest.model_validate(job.payload)
        orchestrator = CorpDevDealOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_earnings_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standing/IR job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = EarningsPackRequest.model_validate(job.payload)
        orchestrator = CorpDevStandingOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Corp Dev job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_DEAL, make_deal_handler(ctx))
    ctx.jobs.register(JOB_KIND_EARNINGS, make_earnings_handler(ctx))
