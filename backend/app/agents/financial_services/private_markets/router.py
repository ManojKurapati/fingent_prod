"""FastAPI router for the Private Markets group-agent (auto-discovered).

* ``POST /agents/private-markets/deals`` — enqueue the hybrid underwriting run;
  returns a ``job_id``. Progress streams over ``GET /jobs/{job_id}/events``; the
  capital commitment surfaces in the shared ``GET /approvals`` queue as the
  Investment Committee approval gate (default-deny).
* ``POST /agents/private-markets/monitor`` — enqueue the standalone stewardship run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.private_markets.schemas import (
    DealRequest,
    MonitorRequest,
    RunAccepted,
)
from app.agents.financial_services.private_markets.service import (
    JOB_KIND_DEAL,
    JOB_KIND_MONITOR,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/private-markets", tags=["private-markets"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _deal_key(request: DealRequest) -> str:
    """Stable idempotency key so a re-submitted identical deal is not double-run."""
    return f"private-markets.deal:{request.deal_id}:{request.asset_class}"


@router.post("/deals", response_model=RunAccepted)
async def deals(request: DealRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_DEAL, request.model_dump(), idempotency_key=_deal_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/monitor", response_model=RunAccepted)
async def monitor(request: MonitorRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_MONITOR, request.model_dump())
    return RunAccepted(job_id=job.id)
