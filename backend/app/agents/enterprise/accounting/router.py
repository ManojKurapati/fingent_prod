"""FastAPI router for the Accounting & Controllership group-agent (auto-discovered).

* ``POST /agents/accounting/close/start`` — enqueue the hybrid period-close run;
  returns a ``job_id`` immediately. Progress streams over
  ``GET /jobs/{job_id}/events``; the GL journal-entry post surfaces in the shared
  ``GET /approvals`` queue and is held until a Controller approves it.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.accounting.schemas import CloseRequest, RunAccepted
from app.agents.enterprise.accounting.service import JOB_KIND_CLOSE, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/accounting", tags=["accounting"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _close_key(request: CloseRequest) -> str:
    """Stable idempotency key so a re-submitted identical close is not double-run."""
    entities = ",".join(sorted(request.entities))
    return f"accounting.close:{request.period}:{entities}"


@router.post("/close/start", response_model=RunAccepted)
async def close_start(request: CloseRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_CLOSE, request.model_dump(), idempotency_key=_close_key(request)
    )
    return RunAccepted(job_id=job.id)
