"""FastAPI router for the Risk Management group-agent (auto-discovered).

* ``POST /agents/risk/run`` — enqueue the parallel risk fan-out + aggregation run;
  returns a ``job_id``. A breach escalates a CRO limit-override to the shared
  ``GET /approvals`` queue (default-deny).
* ``POST /agents/risk/gate/pre-trade`` and ``/agents/risk/gate/limit-check`` — the
  **synchronous** mandatory gates every other agent calls before committing
  capital. They are fail-closed (missing limit -> DENY) and return a token only on
  PASS — the calling agent's consequential endpoint requires it.

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.risk.schemas import (
    GateDecisionResponse,
    LimitCheckRequest,
    PreTradeGateRequest,
    RiskRunRequest,
    RunAccepted,
)
from app.agents.financial_services.risk.service import JOB_KIND_RISK_RUN, register
from app.agents.financial_services.risk.subagents import limit_check_gate, pre_trade_gate
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/risk", tags=["risk"])

Ctx = Annotated[AppContext, Depends(get_context)]


def _run_key(request: RiskRunRequest) -> str:
    return f"risk.run:{request.as_of}:{request.book}"


@router.post("/run", response_model=RunAccepted)
async def run(request: RiskRunRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_RISK_RUN, request.model_dump(), idempotency_key=_run_key(request)
    )
    return RunAccepted(job_id=job.id)


@router.post("/gate/pre-trade", response_model=GateDecisionResponse)
async def gate_pre_trade(request: PreTradeGateRequest, ctx: Ctx) -> GateDecisionResponse:
    decision = await pre_trade_gate(ctx.connectors, request.book, request.notional)
    return GateDecisionResponse(
        decision=decision.decision,
        reason=decision.reason,
        token=decision.token,
        headroom=decision.headroom,
    )


@router.post("/gate/limit-check", response_model=GateDecisionResponse)
async def gate_limit_check(request: LimitCheckRequest, ctx: Ctx) -> GateDecisionResponse:
    decision = await limit_check_gate(ctx.connectors, request.book)
    return GateDecisionResponse(
        decision=decision.decision,
        reason=decision.reason,
        token=decision.token,
        headroom=decision.headroom,
    )
