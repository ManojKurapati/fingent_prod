"""FastAPI router for the Treasury group-agent (auto-discovered).

* ``POST /agents/treasury/daily-position`` — enqueue the hybrid morning sequence
  (sequential spine + parallel tail); returns a ``job_id``. Progress streams over
  ``GET /jobs/{job_id}/events``; the result is the liquidity dashboard payload.
* ``POST /agents/treasury/hedge/execute`` and ``POST /agents/treasury/sweep`` —
  gated **cash-movement** endpoints. Each submits a consequential tool to the
  guardrail engine (default-deny); the action is held in the shared
  ``GET /approvals`` queue until a Treasurer approves it.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.enterprise.treasury.schemas import (
    DailyPositionRequest,
    GateAccepted,
    HedgeExecuteRequest,
    RunAccepted,
    SweepRequest,
)
from app.agents.enterprise.treasury.service import JOB_KIND_DAILY_POSITION, register
from app.agents.enterprise.treasury.subagents import ExecuteHedgeTool, ExecuteSweepTool
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/treasury", tags=["treasury"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _position_key(request: DailyPositionRequest) -> str:
    """Stable idempotency key so a re-submitted identical run is not double-executed."""
    accounts = ",".join(sorted(request.accounts))
    return f"treasury.daily-position:{request.as_of}:{accounts}"


@router.post("/daily-position", response_model=RunAccepted)
async def daily_position(request: DailyPositionRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_DAILY_POSITION, request.model_dump(), idempotency_key=_position_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/hedge/execute", response_model=GateAccepted)
async def hedge_execute(request: HedgeExecuteRequest, ctx: Ctx) -> GateAccepted:
    outcome = await ctx.guardrails.submit(
        ExecuteHedgeTool(),
        request.model_dump(),
        actor="treasury",
        approver_role="treasurer",
        rationale=f"execute FX hedge {request.pair} notional {request.notional}",
        evidence=request.model_dump(),
    )
    return GateAccepted(
        executed=outcome.executed,
        approval_id=outcome.request.id if outcome.request else None,
    )


@router.post("/sweep", response_model=GateAccepted)
async def sweep(request: SweepRequest, ctx: Ctx) -> GateAccepted:
    outcome = await ctx.guardrails.submit(
        ExecuteSweepTool(),
        request.model_dump(),
        actor="treasury",
        approver_role="treasurer",
        rationale=(f"sweep {request.amount} from {request.from_account} to {request.to_account}"),
        evidence=request.model_dump(),
    )
    return GateAccepted(
        executed=outcome.executed,
        approval_id=outcome.request.id if outcome.request else None,
    )
