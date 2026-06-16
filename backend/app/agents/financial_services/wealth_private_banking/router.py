"""FastAPI router for the Wealth & Private Banking group-agent (auto-discovered).

* ``POST /agents/wealth-private-banking/clients`` — enqueue the hybrid
  onboarding+plan run; returns a ``job_id``.
* ``POST /agents/wealth-private-banking/rebalance`` — suitability-gated discretionary
  rebalance; the asset move surfaces in ``GET /approvals`` (default-deny) only if the
  suitability gate PASSes.
* ``POST /agents/wealth-private-banking/credit`` — credit-gated Lombard facility;
  the credit extension is held for approval only if the credit gate PASSes.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.wealth_private_banking.schemas import (
    CreditRequest,
    OnboardRequest,
    RebalanceRequest,
    RunAccepted,
)
from app.agents.financial_services.wealth_private_banking.service import (
    JOB_KIND_CREDIT,
    JOB_KIND_ONBOARD,
    JOB_KIND_REBALANCE,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/wealth-private-banking", tags=["wealth-private-banking"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/clients", response_model=RunAccepted)
async def clients(request: OnboardRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_ONBOARD,
        request.model_dump(),
        idempotency_key=f"wealth.onboard:{request.client_id}",
    )
    return RunAccepted(job_id=job.id)


@router.post("/rebalance", response_model=RunAccepted)
async def rebalance(request: RebalanceRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_REBALANCE, request.model_dump())
    return RunAccepted(job_id=job.id)


@router.post("/credit", response_model=RunAccepted)
async def credit(request: CreditRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_CREDIT, request.model_dump())
    return RunAccepted(job_id=job.id)
