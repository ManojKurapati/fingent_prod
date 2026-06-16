"""FastAPI router for the Finance Systems & Operations group-agent (auto-discovered).

* ``POST /agents/finops/pipeline/run`` — enqueue the hybrid operations run (data
  spine + parallel lanes); returns a ``job_id`` immediately. Progress streams over
  ``GET /jobs/{job_id}/events``; any SoD-conflicting access change surfaces in the
  shared ``GET /approvals`` queue.
* ``POST /agents/finops/erp/access-change`` — enqueue the standalone SoD-gated
  access-change run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.finops.schemas import (
    AccessChangeRequest,
    OperationsRequest,
    RunAccepted,
)
from app.agents.enterprise.finops.service import (
    JOB_KIND_ACCESS_CHANGE,
    JOB_KIND_RUN,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/finops", tags=["finops"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _run_key(request: OperationsRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    sources = ",".join(sorted(request.sources))
    changes = ",".join(sorted(request.access_changes))
    return f"finops.run:{request.period}:{sources}:{changes}"


@router.post("/pipeline/run", response_model=RunAccepted)
async def pipeline_run(request: OperationsRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_RUN, request.model_dump(), idempotency_key=_run_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/erp/access-change", response_model=RunAccepted)
async def access_change(request: AccessChangeRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(
        JOB_KIND_ACCESS_CHANGE,
        request.model_dump(),
        idempotency_key=f"finops.access:{request.role}:{request.change}",
    )
    return RunAccepted(job_id=job.id)
