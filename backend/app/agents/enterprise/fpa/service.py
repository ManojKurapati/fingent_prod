"""Wire the FP&A orchestrators into the job system.

Two job kinds — the hybrid forecast run and the standalone scenario run — each run
their orchestrator in a worker and forward every subagent lifecycle event onto the
job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.fpa.orchestrator import FpaOrchestrator, FpaScenarioOrchestrator
from app.agents.enterprise.fpa.schemas import ForecastRequest, ScenarioRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_FORECAST = "fpa.forecast"
JOB_KIND_SCENARIO = "fpa.scenario"


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


def make_forecast_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the forecast job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ForecastRequest.model_validate(job.payload)
        orchestrator = FpaOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_scenario_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone scenario job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ScenarioRequest.model_validate(job.payload)
        orchestrator = FpaScenarioOrchestrator(
            gateway=ctx.gateway,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both FP&A job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_FORECAST, make_forecast_handler(ctx))
    ctx.jobs.register(JOB_KIND_SCENARIO, make_scenario_handler(ctx))
