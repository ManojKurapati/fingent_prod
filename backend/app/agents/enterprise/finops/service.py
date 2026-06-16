"""Wire the Finance Systems & Operations orchestrators into the job system.

Two job kinds — the hybrid operations run and the standalone SoD-gated access
change — each run their orchestrator in a worker and forward every subagent
lifecycle event onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.finops.orchestrator import (
    FinOpsAccessChangeOrchestrator,
    FinOpsOrchestrator,
)
from app.agents.enterprise.finops.schemas import AccessChangeRequest, OperationsRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_RUN = "finops.run"
JOB_KIND_ACCESS_CHANGE = "finops.access_change"


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


def make_run_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the operations-run job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = OperationsRequest.model_validate(job.payload)
        orchestrator = FinOpsOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_access_change_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone access-change job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = AccessChangeRequest.model_validate(job.payload)
        orchestrator = FinOpsAccessChangeOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Finance Ops job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_RUN, make_run_handler(ctx))
    ctx.jobs.register(JOB_KIND_ACCESS_CHANGE, make_access_change_handler(ctx))
