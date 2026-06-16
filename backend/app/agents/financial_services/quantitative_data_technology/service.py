"""Wire the Quant/Data/Tech orchestrators into the job system."""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.quantitative_data_technology.orchestrator import (
    QuantPromoteOrchestrator,
    QuantResearchOrchestrator,
)
from app.agents.financial_services.quantitative_data_technology.schemas import (
    PromoteRequest,
    QuantJobsRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_JOBS = "quant.jobs"
JOB_KIND_PROMOTE = "quant.promote"


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


def make_jobs_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the parallel research fan-out job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = QuantJobsRequest.model_validate(job.payload)
        orchestrator = QuantResearchOrchestrator(gateway=ctx.gateway)
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_promote_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the validation-gated promotion job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = PromoteRequest.model_validate(job.payload)
        orchestrator = QuantPromoteOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Quant job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_JOBS, make_jobs_handler(ctx))
    ctx.jobs.register(JOB_KIND_PROMOTE, make_promote_handler(ctx))
