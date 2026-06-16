"""Wire the Treasury daily-position orchestrator into the job system.

The daily-position job runs the orchestrator in a worker and forwards every
subagent lifecycle event onto the job's progress stream (SSE). The consequential
hedge/sweep executions are not jobs — they are submitted to the guardrail engine
directly from the router (default-deny).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.treasury.orchestrator import TreasuryDailyPositionOrchestrator
from app.agents.enterprise.treasury.schemas import DailyPositionRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_DAILY_POSITION = "treasury.daily-position"


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


def make_daily_position_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the daily-position job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = DailyPositionRequest.model_validate(job.payload)
        orchestrator = TreasuryDailyPositionOrchestrator(
            gateway=ctx.gateway,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the Treasury daily-position job handler."""
    ctx.jobs.register(JOB_KIND_DAILY_POSITION, make_daily_position_handler(ctx))
