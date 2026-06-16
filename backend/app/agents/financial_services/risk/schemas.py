"""Typed request/response schemas for the Risk Management group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskRunRequest(BaseModel):
    """Intake for the enterprise risk run (parallel measures -> aggregation)."""

    as_of: str = Field(min_length=1)
    book: str = Field(min_length=1)


class PreTradeGateRequest(BaseModel):
    """Intake for the synchronous pre-trade risk gate other agents call."""

    book: str = Field(min_length=1)
    notional: float = Field(gt=0.0)


class LimitCheckRequest(BaseModel):
    """Intake for the synchronous limit-check gate."""

    book: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str


class GateDecisionResponse(BaseModel):
    """Synchronous gate decision returned to the calling agent."""

    decision: str  # "PASS" | "DENY"
    reason: str
    token: str | None
    headroom: float
