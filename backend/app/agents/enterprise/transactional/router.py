"""FastAPI router for the Transactional group-agent (auto-discovered).

* ``POST /agents/transactional/cycle/run`` — enqueue the hybrid operational cycle;
  returns a ``job_id`` immediately. Progress streams over ``GET /jobs/{id}/events``;
  any cash movement surfaces in the shared ``GET /approvals`` queue (default-deny).
* ``POST /agents/transactional/ap/run`` — enqueue the standalone parallel AP run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.transactional.schemas import (
    CycleRequest,
    PaymentRunRequest,
    RunAccepted,
)
from app.agents.enterprise.transactional.service import (
    JOB_KIND_CYCLE,
    JOB_KIND_PAYMENT_RUN,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/transactional", tags=["transactional"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _cycle_key(request: CycleRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    vendors = ",".join(sorted(request.vendors))
    customers = ",".join(sorted(request.customers))
    employees = ",".join(sorted(request.employees))
    return f"transactional.cycle:{request.period}:{vendors}:{customers}:{employees}"


@router.post("/cycle/run", response_model=RunAccepted)
async def cycle_run(request: CycleRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_CYCLE, request.model_dump(), idempotency_key=_cycle_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/ap/run", response_model=RunAccepted)
async def ap_run(request: PaymentRunRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_PAYMENT_RUN, request.model_dump())
    return RunAccepted(job_id=job.id)
