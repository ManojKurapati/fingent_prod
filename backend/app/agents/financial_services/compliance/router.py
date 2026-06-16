"""FastAPI router for the Compliance group-agent (auto-discovered).

* ``POST /agents/compliance/screen`` — enqueue the hybrid screening run (parallel
  AML ‖ sanctions -> disposition); returns a ``job_id``.
* ``POST /agents/compliance/continuous`` — enqueue the parallel continuous-functions run.
* ``POST /agents/compliance/gate/check`` — the **synchronous** conduct/screening gate
  every other agent calls before client-facing, market, or filing actions
  (PASS/HOLD/DENY; fail-closed; token only on PASS).
* ``POST /agents/compliance/sar`` — **gated** SAR filing. Filing externally is
  consequential, routed through the guardrail engine (default-deny).

Exposing a module-level ``router`` is all that's needed for
:mod:`app.agents.discovery` to mount it — no shared registry is edited.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.compliance.schemas import (
    ContinuousRequest,
    GateAccepted,
    GateCheckRequest,
    GateCheckResponse,
    RunAccepted,
    SarRequest,
    ScreenRequest,
)
from app.agents.financial_services.compliance.service import (
    JOB_KIND_CONTINUOUS,
    JOB_KIND_SCREEN,
    register,
)
from app.agents.financial_services.compliance.subagents import FileSarTool, compliance_gate
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/compliance", tags=["compliance"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/screen", response_model=RunAccepted)
async def screen(request: ScreenRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_SCREEN,
        request.model_dump(),
        idempotency_key=f"compliance.screen:{request.subject}",
    )
    return RunAccepted(job_id=job.id)


@router.post("/continuous", response_model=RunAccepted)
async def continuous(request: ContinuousRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)
    job = await ctx.jobs.enqueue(JOB_KIND_CONTINUOUS, request.model_dump())
    return RunAccepted(job_id=job.id)


@router.post("/gate/check", response_model=GateCheckResponse)
async def gate_check(request: GateCheckRequest, ctx: Ctx) -> GateCheckResponse:
    decision = await compliance_gate(ctx.connectors, request.subject)
    return GateCheckResponse(
        decision=decision.decision, reason=decision.reason, token=decision.token
    )


@router.post("/sar", response_model=GateAccepted)
async def file_sar(request: SarRequest, ctx: Ctx) -> GateAccepted:
    outcome = await ctx.guardrails.submit(
        FileSarTool(),
        request.model_dump(),
        actor="compliance",
        approver_role="mlro",
        rationale=f"file SAR on {request.subject}",
        evidence=request.model_dump(),
    )
    return GateAccepted(
        executed=outcome.executed,
        approval_id=outcome.request.id if outcome.request else None,
    )
