"""Wire the Tax orchestrators into the job system.

Two job kinds — the hybrid provision run and the standalone external filing —
each run their orchestrator in a worker and forward every subagent lifecycle event
onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.tax.orchestrator import TaxFilingOrchestrator, TaxProvisionOrchestrator
from app.agents.enterprise.tax.schemas import FileRequest, ProvisionRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_PROVISION = "tax.provision"
JOB_KIND_FILE = "tax.file"


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


def make_provision_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the provision job handler bound to the shared application context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ProvisionRequest.model_validate(job.payload)
        orchestrator = TaxProvisionOrchestrator(
            gateway=ctx.gateway,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_file_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the external-filing job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = FileRequest.model_validate(job.payload)
        orchestrator = TaxFilingOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Tax job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_PROVISION, make_provision_handler(ctx))
    ctx.jobs.register(JOB_KIND_FILE, make_file_handler(ctx))
