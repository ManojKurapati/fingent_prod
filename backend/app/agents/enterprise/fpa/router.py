"""FastAPI router for the FP&A group-agent (auto-discovered).

* ``POST /agents/fpa/forecast`` — enqueue the hybrid planning run; returns a
  ``job_id`` immediately. Progress streams over ``GET /jobs/{job_id}/events``;
  any variance-commentary request surfaces in the shared ``GET /approvals`` queue.
* ``POST /agents/fpa/scenario`` — enqueue the standalone scenario run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.fpa.schemas import ForecastRequest, RunAccepted, ScenarioRequest
from app.agents.enterprise.fpa.service import (
    JOB_KIND_FORECAST,
    JOB_KIND_SCENARIO,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/fpa", tags=["fpa"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _forecast_key(request: ForecastRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    ccs = ",".join(sorted(request.cost_centres))
    return f"fpa.forecast:{request.period}:{ccs}:{request.variance_threshold}"


@router.post("/forecast", response_model=RunAccepted)
async def forecast(request: ForecastRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_FORECAST, request.model_dump(), idempotency_key=_forecast_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/scenario", response_model=RunAccepted)
async def scenario(request: ScenarioRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_SCENARIO, request.model_dump())
    return RunAccepted(job_id=job.id)
