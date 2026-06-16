"""FastAPI router for the Internal Audit & Controls group-agent (auto-discovered).

* ``POST /agents/audit/engagement`` — enqueue the sequenced engagement run; returns
  a ``job_id`` immediately. Progress streams over ``GET /jobs/{job_id}/events``; the
  report-issuance request surfaces in the shared ``GET /approvals`` queue (CAE gate).

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.audit.schemas import EngagementRequest, RunAccepted
from app.agents.enterprise.audit.service import JOB_KIND_ENGAGEMENT, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/audit", tags=["audit"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _engagement_key(request: EngagementRequest) -> str:
    """Stable idempotency key so a re-submitted identical engagement is not re-run."""
    controls = ",".join(sorted(request.controls))
    return f"audit.engagement:{request.engagement}:{controls}"


@router.post("/engagement", response_model=RunAccepted)
async def engagement(request: EngagementRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_ENGAGEMENT, request.model_dump(), idempotency_key=_engagement_key(request)
    )
    return RunAccepted(job_id=job.id)
