"""FastAPI router for the Investment Banking group-agent (auto-discovered).

* ``POST /agents/investment-banking/mandates`` — enqueue the hybrid mandate run;
  returns a ``job_id`` immediately. Progress streams over ``GET /jobs/{id}/events``;
  the client-facing launch surfaces in the shared ``GET /approvals`` queue (and is
  withheld entirely when the compliance gate denies).

Exposing a module-level ``router`` is all that's needed for auto-discovery.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.investment_banking.schemas import MandateRequest, RunAccepted
from app.agents.financial_services.investment_banking.service import JOB_KIND_MANDATE, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/investment-banking", tags=["investment-banking"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _mandate_key(request: MandateRequest) -> str:
    """Stable idempotency key so a re-submitted identical mandate is not double-run."""
    return f"ib.mandate:{request.deal_id}:{request.deal_type}"


@router.post("/mandates", response_model=RunAccepted)
async def create_mandate(request: MandateRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_MANDATE, request.model_dump(), idempotency_key=_mandate_key(request)
    )
    return RunAccepted(job_id=job.id)
