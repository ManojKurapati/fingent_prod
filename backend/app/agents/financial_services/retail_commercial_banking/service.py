"""Wire the Retail & Commercial Banking orchestrator into the job system.

The lending pipeline runs in a worker; each subagent's lifecycle event is forwarded
onto the job's progress stream (SSE) so the React kanban can green stages as they
complete.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.retail_commercial_banking.orchestrator import (
    RetailBankingOrchestrator,
)
from app.agents.financial_services.retail_commercial_banking.schemas import ApplicationRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_APPLICATION = "retail-commercial-banking.application"


def make_application_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the lending-pipeline job handler bound to the shared context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ApplicationRequest.model_validate(job.payload)
        orchestrator = RetailBankingOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
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
    """Idempotently register the lending-pipeline job handler on the shared queue."""
    ctx.jobs.register(JOB_KIND_APPLICATION, make_application_handler(ctx))
