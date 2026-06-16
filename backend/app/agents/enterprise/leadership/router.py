"""FastAPI router for the Leadership group-agent (auto-discovered).

* ``POST /agents/leadership/board-pack`` — enqueue the hybrid synthesis run;
  returns a ``job_id`` immediately. Progress streams over
  ``GET /jobs/{job_id}/events``; the board-pack publication surfaces in the shared
  ``GET /approvals`` queue (CFO gate).
* ``POST /agents/leadership/capital-scenario`` — enqueue the standalone capital run.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.leadership.schemas import (
    BoardPackRequest,
    CapitalScenarioRequest,
    RunAccepted,
)
from app.agents.enterprise.leadership.service import (
    JOB_KIND_BOARD_PACK,
    JOB_KIND_CAPITAL,
    register,
)
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/leadership", tags=["leadership"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _board_pack_key(request: BoardPackRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    divs = ",".join(sorted(request.divisions))
    return f"leadership.board_pack:{request.period}:{divs}:{request.target_leverage}"


@router.post("/board-pack", response_model=RunAccepted)
async def board_pack(request: BoardPackRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_BOARD_PACK, request.model_dump(), idempotency_key=_board_pack_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/capital-scenario", response_model=RunAccepted)
async def capital_scenario(request: CapitalScenarioRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_CAPITAL, request.model_dump())
    return RunAccepted(job_id=job.id)
