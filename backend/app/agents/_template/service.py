"""Wiring the template orchestrator into the job system.

The job handler runs the orchestrator and forwards each subagent's lifecycle
events onto the job's progress stream (SSE). Register the handler once at app
startup (see :func:`register`).

COPY THIS FILE.
"""

from __future__ import annotations

from typing import Any

from app.agents._template.orchestrator import TemplateOrchestrator
from app.agents._template.schemas import RunRequest
from app.agents.core import StepEvent
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND = "template.run"


def make_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = RunRequest.model_validate(job.payload)
        orchestrator = TemplateOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            correlation_id=job.id,
        )

        async def step_emit(event: StepEvent) -> None:
            await emit(
                ProgressEvent(
                    job_id=job.id,
                    type="step",
                    payload={"step": event.step, "status": event.status.value},
                )
            )

        result = await orchestrator.run(request, emit=step_emit)
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the template job handler on the shared queue."""
    ctx.jobs.register(JOB_KIND, make_handler(ctx))
