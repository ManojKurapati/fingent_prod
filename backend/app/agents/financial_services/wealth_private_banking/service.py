"""Wire the Wealth & Private Banking orchestrators into the job system.

Three job kinds — hybrid onboarding+plan, suitability-gated rebalance, and
credit-gated Lombard lending — each run their orchestrator in a worker and forward
every subagent lifecycle event onto the job's progress stream (SSE).
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.wealth_private_banking.orchestrator import (
    CreditOrchestrator,
    RebalanceOrchestrator,
    WealthOnboardingOrchestrator,
)
from app.agents.financial_services.wealth_private_banking.schemas import (
    CreditRequest,
    OnboardRequest,
    RebalanceRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_ONBOARD = "wealth-private-banking.onboard"
JOB_KIND_REBALANCE = "wealth-private-banking.rebalance"
JOB_KIND_CREDIT = "wealth-private-banking.credit"


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


def make_onboard_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the onboarding+plan job handler bound to the shared context."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = OnboardRequest.model_validate(job.payload)
        orchestrator = WealthOnboardingOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_rebalance_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the suitability-gated rebalance job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = RebalanceRequest.model_validate(job.payload)
        orchestrator = RebalanceOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_credit_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    """Build the credit-gated Lombard lending job handler."""

    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = CreditRequest.model_validate(job.payload)
        orchestrator = CreditOrchestrator(
            gateway=ctx.gateway,
            guardrails=ctx.guardrails,
            connectors=ctx.connectors,
            correlation_id=job.id,
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register all three job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_ONBOARD, make_onboard_handler(ctx))
    ctx.jobs.register(JOB_KIND_REBALANCE, make_rebalance_handler(ctx))
    ctx.jobs.register(JOB_KIND_CREDIT, make_credit_handler(ctx))
