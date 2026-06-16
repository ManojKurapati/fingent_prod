"""Wire the Transactional orchestrators into the job system.

Two job kinds — the hybrid operational cycle and the standalone AP payment run —
each run their orchestrator in a worker and forward every subagent lifecycle event
onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.enterprise.transactional.orchestrator import (
    ApPaymentRunOrchestrator,
    TransactionalOrchestrator,
)
from app.agents.enterprise.transactional.schemas import CycleRequest, PaymentRunRequest
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_CYCLE = "transactional.cycle"
JOB_KIND_PAYMENT_RUN = "transactional.payment_run"


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


def make_cycle_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the operational-cycle job handler bound to the shared context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = CycleRequest.model_validate(job.payload)
        orchestrator = TransactionalOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_payment_run_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the standalone AP payment-run job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = PaymentRunRequest.model_validate(job.payload)
        orchestrator = ApPaymentRunOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register both Transactional job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_CYCLE, make_cycle_handler(ctx))
    ctx.jobs.register(JOB_KIND_PAYMENT_RUN, make_payment_run_handler(ctx))
