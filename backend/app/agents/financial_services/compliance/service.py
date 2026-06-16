"""Wire the Compliance orchestrators into the job system.

Two job kinds — the screening run (hybrid) and the continuous-functions run
(parallel) — execute their orchestrator in a worker and forward every subagent
lifecycle event onto the job's progress stream (SSE). The synchronous gate and the
gated SAR filing are answered inline from the router, not as jobs.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.compliance.orchestrator import (
    ComplianceContinuousOrchestrator,
    ComplianceScreenOrchestrator,
)
from app.agents.financial_services.compliance.schemas import ContinuousRequest, ScreenRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_SCREEN = "compliance.screen"
JOB_KIND_CONTINUOUS = "compliance.continuous"


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


def make_screen_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ScreenRequest.model_validate(job.payload)
        orchestrator = ComplianceScreenOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_continuous_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ContinuousRequest.model_validate(job.payload)
        orchestrator = ComplianceContinuousOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the Compliance job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_SCREEN, make_screen_handler(ctx))
    ctx.jobs.register(JOB_KIND_CONTINUOUS, make_continuous_handler(ctx))
