"""Typed request/response schemas for the Treasury group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DailyPositionRequest(BaseModel):
    """Intake for the morning daily-position sequence (drives the hybrid run)."""

    as_of: str = Field(min_length=1)
    accounts: list[str] = Field(min_length=1)


class HedgeExecuteRequest(BaseModel):
    """Intake for a gated FX-hedge execution (cash-movement)."""

    pair: str = Field(min_length=1)
    notional: float = Field(gt=0.0)


class SweepRequest(BaseModel):
    """Intake for a gated cash sweep between accounts (cash-movement)."""

    from_account: str = Field(min_length=1)
    to_account: str = Field(min_length=1)
    amount: float = Field(gt=0.0)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str


class GateAccepted(BaseModel):
    """Returned after submitting a consequential cash-movement to the guardrail engine."""

    executed: bool
    approval_id: str | None
