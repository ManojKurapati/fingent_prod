"""Typed request/response schemas for the Insurance group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubmissionRequest(BaseModel):
    """Intake for a risk submission (drives the hybrid pricing fan-out)."""

    submission_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    peril: str = Field(min_length=1)
    tiv: float = Field(gt=0.0)  # total insured value / exposure


class PortfolioRequest(BaseModel):
    """Intake for a portfolio-level reinsurance ‖ product optimisation run."""

    region: str = Field(min_length=1)
    product: str = Field(min_length=1)


class ClaimRequest(BaseModel):
    """Intake for opening a claim on the post-bind lifecycle."""

    claim_id: str = Field(min_length=1)
    amount: float = Field(gt=0.0)


class BindRequest(BaseModel):
    """Intake for a gated policy bind (consequential: binds insurance risk)."""

    submission_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    peril: str = Field(min_length=1)
    pml: float = Field(ge=0.0)
    premium: float = Field(gt=0.0)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str


class BindResponse(BaseModel):
    """Outcome of a bind attempt: the accumulation gate plus the guardrail state."""

    gate: str  # "PASS" | "DENY"
    executed: bool
    approval_id: str | None
    reason: str
