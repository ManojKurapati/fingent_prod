"""FastAPI router for the Insurance group-agent (auto-discovered).

* ``POST /agents/insurance/submissions`` — enqueue the hybrid pricing -> underwriting
  run; returns a ``job_id``.
* ``POST /agents/insurance/portfolio`` — enqueue the parallel reinsurance ‖ product run.
* ``POST /agents/insurance/claims`` — enqueue the sequential claims-lifecycle run.
* ``POST /agents/insurance/submissions/bind`` — **gated** bind. Binding insurance
  risk is consequential: it must first clear the mandatory accumulation gate (a hard
  DENY halts the flow), then a default-deny guardrail approval before the policy is
  bound.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.insurance.schemas import (
    BindRequest,
    BindResponse,
    ClaimRequest,
    PortfolioRequest,
    RunAccepted,
    SubmissionRequest,
)
from app.agents.financial_services.insurance.service import (
    JOB_KIND_CLAIMS,
    JOB_KIND_PORTFOLIO,
    JOB_KIND_SUBMISSION,
    register,
)
from app.agents.financial_services.insurance.subagents import BindPolicyTool, accumulation_gate
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/insurance", tags=["insurance"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _submission_key(request: SubmissionRequest) -> str:
    return f"insurance.submission:{request.submission_id}:{request.region}:{request.peril}"


@router.post("/submissions", response_model=RunAccepted)
async def submit(request: SubmissionRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_SUBMISSION, request.model_dump(), idempotency_key=_submission_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/portfolio", response_model=RunAccepted)
async def portfolio(request: PortfolioRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_PORTFOLIO, request.model_dump())
    return RunAccepted(job_id=job.id)


@router.post("/claims", response_model=RunAccepted)
async def claims(request: ClaimRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_CLAIMS, request.model_dump())
    return RunAccepted(job_id=job.id)


@router.post("/submissions/bind", response_model=BindResponse)
async def bind(request: BindRequest, ctx: Ctx) -> BindResponse:
    # MANDATORY pre-execution risk gate: accumulation/appetite. Fail-closed.
    gate = await accumulation_gate(ctx.connectors, request.region, request.peril, request.pml)
    if not gate.passed:
        return BindResponse(
            gate="DENY",
            executed=False,
            approval_id=None,
            reason=(
                f"accumulation gate denied: proposed {gate.proposed} exceeds "
                f"limit {gate.limit} for {request.region}/{request.peril}"
            ),
        )

    # Gate cleared -> still default-deny: hold the bind for human approval.
    outcome = await ctx.guardrails.submit(
        BindPolicyTool(),
        request.model_dump(),
        actor="insurance",
        approver_role="chief-underwriter",
        rationale=f"bind policy {request.submission_id} (premium {request.premium})",
        evidence={"proposed_accumulation": gate.proposed, "limit": gate.limit},
    )
    return BindResponse(
        gate="PASS",
        executed=outcome.executed,
        approval_id=outcome.request.id if outcome.request else None,
        reason="within appetite; awaiting underwriting approval",
    )
