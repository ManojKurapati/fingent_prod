"""FastAPI router for the template group-agent.

Pattern every group follows:
* ``POST /agents/<group>/run`` validates intake, enqueues a background job, and
  returns a ``job_id`` immediately (work runs in the worker, not the request).
* Progress streams over the shared ``GET /jobs/{job_id}/events`` SSE endpoint.
* Consequential actions surface in the shared ``GET /approvals`` queue.

Auto-discovery: exposing a module-level ``router`` named ``router`` is all that is
needed — :mod:`app.agents.discovery` finds it. Do NOT hand-edit a shared registry.

COPY THIS FILE into ``app/agents/enterprise/<group>/router.py`` (or
``financial_services``), renaming ``template`` → your group.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents._template.schemas import RunAccepted, RunRequest
from app.agents._template.service import JOB_KIND, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/template", tags=["template"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/run", response_model=RunAccepted)
async def run(request: RunRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(JOB_KIND, request.model_dump())
    return RunAccepted(job_id=job.id)
