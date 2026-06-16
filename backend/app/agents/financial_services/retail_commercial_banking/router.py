"""FastAPI router for the Retail & Commercial Banking group-agent (auto-discovered).

* ``POST /agents/retail-commercial-banking/applications`` — start the sequential
  lending pipeline; returns a ``job_id``. Stage progression streams over
  ``GET /jobs/{job_id}/events``; the funding disbursement surfaces in the shared
  ``GET /approvals`` queue (default-deny) behind the underwriter decision.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.retail_commercial_banking.schemas import (
    ApplicationRequest,
    RunAccepted,
)
from app.agents.financial_services.retail_commercial_banking.service import (
    JOB_KIND_APPLICATION,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/retail-commercial-banking", tags=["retail-commercial-banking"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/applications", response_model=RunAccepted)
async def applications(request: ApplicationRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_APPLICATION,
        request.model_dump(),
        idempotency_key=f"banking.application:{request.application_id}",
    )
    return RunAccepted(job_id=job.id)
