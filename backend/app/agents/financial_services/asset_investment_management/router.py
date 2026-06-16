"""FastAPI router for the Asset & Investment Management group-agent (auto-discovered).

* ``POST /agents/asset-investment-management/rebalance`` — enqueue the hybrid
  rebalance run; the mandate/risk gate runs in the worker and order placement
  surfaces in the shared ``GET /approvals`` queue (withheld entirely on a gate deny).
* ``POST /agents/asset-investment-management/research`` — enqueue the standalone
  parallel research fan-out.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.asset_investment_management.schemas import (
    RebalanceRequest,
    ResearchRequest,
    RunAccepted,
)
from app.agents.financial_services.asset_investment_management.service import (
    JOB_KIND_REBALANCE,
    JOB_KIND_RESEARCH,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(
    prefix="/agents/asset-investment-management", tags=["asset-investment-management"]
)

Ctx = Annotated[AppContext, Depends(get_context)]


def _rebalance_key(request: RebalanceRequest) -> str:
    """Stable idempotency key so a re-submitted identical rebalance is not double-run."""
    names = ",".join(sorted(request.names))
    return f"aim.rebalance:{request.portfolio_id}:{request.period}:{names}"


@router.post("/rebalance", response_model=RunAccepted)
async def rebalance(request: RebalanceRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_REBALANCE, request.model_dump(), idempotency_key=_rebalance_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/research", response_model=RunAccepted)
async def research(request: ResearchRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_RESEARCH, request.model_dump())
    return RunAccepted(job_id=job.id)
