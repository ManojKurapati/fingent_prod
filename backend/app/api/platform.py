"""Platform-level endpoints shared by every agent — FROZEN CONTRACT.

* Health check.
* The **single human-in-the-loop approval API** (list / approve / reject) that
  governs every consequential action regardless of which agent proposed it.
* Job status and the **SSE progress stream** the React client subscribes to.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.context import AppContext, get_context
from app.guardrails import ApprovalNotFoundError, ApprovalRequest, InvalidTransitionError
from app.jobs import format_sse

router = APIRouter()

Ctx = Annotated[AppContext, Depends(get_context)]


class ApprovalView(BaseModel):
    id: str
    tool_name: str
    actor: str
    approver_role: str
    rationale: str
    state: str
    decided_by: str | None = None

    @classmethod
    def of(cls, req: ApprovalRequest) -> ApprovalView:
        return cls(
            id=req.id,
            tool_name=req.tool_name,
            actor=req.actor,
            approver_role=req.approver_role,
            rationale=req.rationale,
            state=req.state.value,
            decided_by=req.decided_by,
        )


class ApproveBody(BaseModel):
    approver: str


class RejectBody(BaseModel):
    approver: str
    reason: str = ""


class DecisionResult(BaseModel):
    executed: bool
    request: ApprovalView


class JobView(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    result: Any | None = None
    error: str | None = None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/approvals", response_model=list[ApprovalView])
async def list_approvals(ctx: Ctx) -> list[ApprovalView]:
    return [ApprovalView.of(r) for r in ctx.guardrails.pending()]


@router.post("/approvals/{request_id}/approve", response_model=DecisionResult)
async def approve(request_id: str, body: ApproveBody, ctx: Ctx) -> DecisionResult:
    try:
        outcome = await ctx.guardrails.approve(request_id, approver=body.approver)
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="approval request not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    assert outcome.request is not None
    return DecisionResult(executed=outcome.executed, request=ApprovalView.of(outcome.request))


@router.post("/approvals/{request_id}/reject", response_model=DecisionResult)
async def reject(request_id: str, body: RejectBody, ctx: Ctx) -> DecisionResult:
    try:
        outcome = await ctx.guardrails.reject(
            request_id, approver=body.approver, reason=body.reason
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="approval request not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    assert outcome.request is not None
    return DecisionResult(executed=outcome.executed, request=ApprovalView.of(outcome.request))


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, ctx: Ctx) -> JobView:
    try:
        job = ctx.jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return JobView(
        id=job.id,
        kind=job.kind,
        status=job.status.value,
        attempts=job.attempts,
        result=job.result,
        error=job.error,
    )


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, ctx: Ctx) -> EventSourceResponse:
    bus = ctx.jobs.progress

    async def _stream() -> Any:
        async for event in bus.subscribe(job_id):
            yield format_sse(event)

    return EventSourceResponse(_stream())
