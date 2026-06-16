"""FastAPI router for the Operations group-agent (auto-discovered).

* ``POST /agents/ops/process`` — enqueue the hybrid confirm->settle->reconcile
  pipeline; returns a ``job_id`` immediately. Settlement instructions surface in
  the shared ``GET /approvals`` queue (default-deny).
* ``POST /agents/ops/recon`` — enqueue the standalone parallel reconciliation run.

Progress streams over the shared ``GET /jobs/{job_id}/events`` SSE endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.operations_middle_back_office.schemas import (
    OpsReconRequest,
    RunAccepted,
    TradeProcessRequest,
)
from app.agents.financial_services.operations_middle_back_office.service import (
    JOB_KIND_PROCESS,
    JOB_KIND_RECON,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/ops", tags=["ops"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/process", response_model=RunAccepted)
async def process(request: TradeProcessRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_PROCESS,
        request.model_dump(),
        idempotency_key=f"ops.process:{request.trade_id}:{request.amount}",
    )
    return RunAccepted(job_id=job.id)


@router.post("/recon", response_model=RunAccepted)
async def recon(request: OpsReconRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_RECON, request.model_dump())
    return RunAccepted(job_id=job.id)
