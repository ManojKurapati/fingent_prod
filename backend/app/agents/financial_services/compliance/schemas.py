"""Typed request/response schemas for the Compliance group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScreenRequest(BaseModel):
    """Intake for an onboarding/transaction screen (aml ‖ sanctions -> disposition)."""

    subject: str = Field(min_length=1)


class ContinuousRequest(BaseModel):
    """Intake for the parallel continuous-functions run."""

    scope: str = Field(min_length=1)


class GateCheckRequest(BaseModel):
    """Intake for the synchronous compliance gate other agents call."""

    subject: str = Field(min_length=1)
    action: str = Field(min_length=1)


class SarRequest(BaseModel):
    """Intake for a gated suspicious-activity-report filing (external filing)."""

    subject: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    amount: float = Field(ge=0.0)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str


class GateCheckResponse(BaseModel):
    """Synchronous gate decision returned to the calling agent."""

    decision: str  # "PASS" | "HOLD" | "DENY"
    reason: str
    token: str | None


class GateAccepted(BaseModel):
    """Returned after submitting a consequential filing to the guardrail engine."""

    executed: bool
    approval_id: str | None
