"""Wire the Leadership orchestrators into the job system.

Two job kinds — the hybrid board-pack run and the standalone capital-scenario run —
each run their orchestrator in a worker and forward every subagent lifecycle event
onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.leadership.orchestrator import (
    LeadershipCapitalOrchestrator,
    LeadershipOrchestrator,
)
from app.agents.enterprise.leadership.schemas import BoardPackRequest, CapitalScenarioRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_BOARD_PACK = "leadership.board_pack"
JOB_KIND_CAPITAL = "leadership.capital_scenario"


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


def make_board_pack_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the board-pack job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = BoardPackRequest.model_validate(job.payload)
        orchestrator = LeadershipOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_capital_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone capital-scenario job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = CapitalScenarioRequest.model_validate(job.payload)
        orchestrator = LeadershipCapitalOrchestrator(
            gateway=ctx.gateway,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Leadership job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_BOARD_PACK, make_board_pack_handler(ctx))
    ctx.jobs.register(JOB_KIND_CAPITAL, make_capital_handler(ctx))
