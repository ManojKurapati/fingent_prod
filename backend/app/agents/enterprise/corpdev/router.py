"""FastAPI router for the Corp Dev & Strategy group-agent (auto-discovered).

* ``POST /agents/corpdev/deal`` — enqueue the hybrid deal-evaluation run; returns a
  ``job_id`` immediately. Progress streams over ``GET /jobs/{job_id}/events``; the
  deal recommendation surfaces in the shared ``GET /approvals`` queue (board gate).
* ``POST /agents/corpdev/ir/earnings-pack`` — enqueue the parallel standing/IR run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.corpdev.schemas import (
    DealRequest,
    EarningsPackRequest,
    RunAccepted,
)
from app.agents.enterprise.corpdev.service import (
    JOB_KIND_DEAL,
    JOB_KIND_EARNINGS,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/corpdev", tags=["corpdev"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _deal_key(request: DealRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    targets = ",".join(sorted(request.targets))
    return f"corpdev.deal:{targets}:{request.synergy_rate}:{request.ebitda_multiple}"


@router.post("/deal", response_model=RunAccepted)
async def deal(request: DealRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_DEAL, request.model_dump(), idempotency_key=_deal_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/ir/earnings-pack", response_model=RunAccepted)
async def earnings_pack(request: EarningsPackRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_EARNINGS, request.model_dump())
    return RunAccepted(job_id=job.id)
