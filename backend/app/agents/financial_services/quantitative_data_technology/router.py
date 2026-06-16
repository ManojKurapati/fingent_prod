"""FastAPI router for the Quant/Data/Tech group-agent (auto-discovered).

* ``POST /agents/quant/jobs`` — enqueue the parallel research/calibration fan-out.
* ``POST /agents/quant/promote`` — enqueue a validation-gated promotion; the
  ``quant_promote_model`` action surfaces in the shared ``GET /approvals`` queue
  (default-deny) and only runs after the model-validation gate clears.

Progress streams over the shared ``GET /jobs/{job_id}/events`` SSE endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.quantitative_data_technology.schemas import (
    PromoteRequest,
    QuantJobsRequest,
    RunAccepted,
)
from app.agents.financial_services.quantitative_data_technology.service import (
    JOB_KIND_JOBS,
    JOB_KIND_PROMOTE,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/quant", tags=["quant"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/jobs", response_model=RunAccepted)
async def jobs(request: QuantJobsRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(JOB_KIND_JOBS, request.model_dump())
    return RunAccepted(job_id=job.id)


@router.post("/promote", response_model=RunAccepted)
async def promote(request: PromoteRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(
        JOB_KIND_PROMOTE,
        request.model_dump(),
        idempotency_key=f"quant.promote:{request.model_id}:{request.validation_token}",
    )
    return RunAccepted(job_id=job.id)
