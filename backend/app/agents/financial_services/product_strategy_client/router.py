"""FastAPI router for the Product/Strategy/Client group-agent (auto-discovered).

* ``POST /agents/product/initiatives`` — enqueue the discovery -> pricing ->
  filing-gate -> launch chain; the ``product_launch`` action surfaces in the
  shared ``GET /approvals`` queue (default-deny) only after the filing gate clears.
* ``POST /agents/product/commercial`` — enqueue the parallel commercial loop;
  client activation surfaces in approvals only after the KYC gate clears.

Progress streams over the shared ``GET /jobs/{job_id}/events`` SSE endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.product_strategy_client.schemas import (
    CommercialRequest,
    InitiativeRequest,
    RunAccepted,
)
from app.agents.financial_services.product_strategy_client.service import (
    JOB_KIND_COMMERCIAL,
    JOB_KIND_INITIATIVE,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/product", tags=["product"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/initiatives", response_model=RunAccepted)
async def initiatives(request: InitiativeRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_INITIATIVE,
        request.model_dump(),
        idempotency_key=f"product.initiative:{request.name}:{request.filing_token}",
    )
    return RunAccepted(job_id=job.id)


@router.post("/commercial", response_model=RunAccepted)
async def commercial(request: CommercialRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(
        JOB_KIND_COMMERCIAL,
        request.model_dump(),
        idempotency_key=f"product.commercial:{request.client_id}:{request.kyc_token}",
    )
    return RunAccepted(job_id=job.id)
