"""Wire the Operations orchestrators into the job system."""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.operations_middle_back_office.orchestrator import (
    OpsPipelineOrchestrator,
    OpsReconOrchestrator,
)
from app.agents.financial_services.operations_middle_back_office.schemas import (
    OpsReconRequest,
    TradeProcessRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_PROCESS = "ops.process"
JOB_KIND_RECON = "ops.recon"


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


def make_process_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the confirm->settle->reconcile job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = TradeProcessRequest.model_validate(job.payload)
        orchestrator = OpsPipelineOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_recon_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone parallel reconciliation job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = OpsReconRequest.model_validate(job.payload)
        orchestrator = OpsReconOrchestrator(gateway=ctx.gateway, connectors=ctx.connectors)
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Operations job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_PROCESS, make_process_handler(ctx))
    ctx.jobs.register(JOB_KIND_RECON, make_recon_handler(ctx))
