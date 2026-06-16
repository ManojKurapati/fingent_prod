"""Wire the Asset & Investment Management orchestrators into the job system.

Two job kinds — the hybrid rebalance run and the standalone parallel research
run — each run their orchestrator in a worker and forward every subagent lifecycle
event onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.asset_investment_management.orchestrator import (
    AimRebalanceOrchestrator,
    AimResearchOrchestrator,
)
from app.agents.financial_services.asset_investment_management.schemas import (
    RebalanceRequest,
    ResearchRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_REBALANCE = "asset-investment-management.rebalance"
JOB_KIND_RESEARCH = "asset-investment-management.research"


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


def make_rebalance_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the rebalance job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = RebalanceRequest.model_validate(job.payload)
        orchestrator = AimRebalanceOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_research_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone research job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ResearchRequest.model_validate(job.payload)
        orchestrator = AimResearchOrchestrator(gateway=ctx.gateway, correlation_id=job.id)
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both AIM job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_REBALANCE, make_rebalance_handler(ctx))
    ctx.jobs.register(JOB_KIND_RESEARCH, make_research_handler(ctx))
