"""Wire the Investment Banking orchestrator into the job system.

The handler runs the hybrid mandate orchestrator in a worker and forwards every
subagent lifecycle event onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.investment_banking.orchestrator import (
    InvestmentBankingOrchestrator,
)
from app.agents.financial_services.investment_banking.schemas import MandateRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_MANDATE = "investment-banking.mandate"


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


def make_mandate_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the mandate job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = MandateRequest.model_validate(job.payload)
        orchestrator = InvestmentBankingOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the mandate job handler on the shared queue."""
    ctx.jobs.register(JOB_KIND_MANDATE, make_mandate_handler(ctx))
