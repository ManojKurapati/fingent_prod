"""FastAPI router for the Tax group-agent (auto-discovered).

* ``POST /agents/tax/provision`` — enqueue the hybrid provision run; returns a
  ``job_id`` immediately. Progress streams over ``GET /jobs/{id}/events``.
* ``POST /agents/tax/file/{return_id}`` — enqueue a gated external filing; the
  submission surfaces in the shared ``GET /approvals`` queue (default-deny).

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents.enterprise.tax.schemas import FileRequest, ProvisionRequest, RunAccepted
from app.agents.enterprise.tax.service import JOB_KIND_FILE, JOB_KIND_PROVISION, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/tax", tags=["tax"])

Ctx = Annotated[AppContext, Depends(get_context)]


class FileBody(BaseModel):
    """Request body for a filing (``return_id`` is taken from the path)."""

    jurisdiction: str = Field(min_length=1)


def _provision_key(request: ProvisionRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    js = ",".join(sorted(request.jurisdictions))
    return f"tax.provision:{request.period}:{js}"


@router.post("/provision", response_model=RunAccepted)
async def provision(request: ProvisionRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_PROVISION, request.model_dump(), idempotency_key=_provision_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/file/{return_id}", response_model=RunAccepted)
async def file_return(return_id: str, body: FileBody, ctx: Ctx) -> RunAccepted:
    register(ctx)
    request = FileRequest(return_id=return_id, jurisdiction=body.jurisdiction)
    job = await ctx.jobs.enqueue(
        JOB_KIND_FILE,
        request.model_dump(),
        idempotency_key=f"tax.file:{return_id}",
    )
    return RunAccepted(job_id=job.id)
