"""Wire the Insurance orchestrators into the job system.

Three job kinds — submission (hybrid pricing -> underwriting), portfolio (parallel
reinsurance ‖ product), and claims (sequential) — each run their orchestrator in a
worker and forward every subagent lifecycle event onto the job's progress stream
(SSE). The consequential policy bind is not a job — it is gated from the router.
"""

from __future__ import annotations

from typing import Any

from app.agents.core import StepEvent
from app.agents.financial_services.insurance.orchestrator import (
    InsuranceClaimsOrchestrator,
    InsurancePortfolioOrchestrator,
    InsuranceSubmissionOrchestrator,
)
from app.agents.financial_services.insurance.schemas import (
    ClaimRequest,
    PortfolioRequest,
    SubmissionRequest,
)
from app.api.context import AppContext
from app.jobs import Emit, Job, ProgressEvent

JOB_KIND_SUBMISSION = "insurance.submission"
JOB_KIND_PORTFOLIO = "insurance.portfolio"
JOB_KIND_CLAIMS = "insurance.claims"


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


def make_submission_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = SubmissionRequest.model_validate(job.payload)
        orchestrator = InsuranceSubmissionOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_portfolio_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = PortfolioRequest.model_validate(job.payload)
        orchestrator = InsurancePortfolioOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def make_claims_handler(ctx: AppContext):  # type: ignore[no-untyped-def]
    async def handler(job: Job, emit: Emit) -> dict[str, Any]:
        request = ClaimRequest.model_validate(job.payload)
        orchestrator = InsuranceClaimsOrchestrator(
            gateway=ctx.gateway, connectors=ctx.connectors, correlation_id=job.id
        )
        result = await orchestrator.run(request, emit=_forward(job.id, emit))
        return result.outputs

    return handler


def register(ctx: AppContext) -> None:
    """Idempotently register the Insurance job handlers on the shared queue."""
    ctx.jobs.register(JOB_KIND_SUBMISSION, make_submission_handler(ctx))
    ctx.jobs.register(JOB_KIND_PORTFOLIO, make_portfolio_handler(ctx))
    ctx.jobs.register(JOB_KIND_CLAIMS, make_claims_handler(ctx))
