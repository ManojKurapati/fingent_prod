"""Wire the Internal Audit orchestrator into the job system.

The engagement job runs the orchestrator in a worker and forwards every subagent
lifecycle event onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.audit.orchestrator import AuditEngagementOrchestrator
from app.agents.enterprise.audit.schemas import EngagementRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_ENGAGEMENT = "audit.engagement"


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


def make_engagement_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the engagement job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = EngagementRequest.model_validate(job.payload)
        orchestrator = AuditEngagementOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the Internal Audit job handler on the shared queue."""
    ctx.jobs.register(JOB_KIND_ENGAGEMENT, make_engagement_handler(ctx))
