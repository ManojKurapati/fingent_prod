"""Typed request/response schemas for the Wealth & Private Banking group-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Segment = Literal["hnw", "uhnw"]
Facility = Literal["lombard", "mortgage"]


class OnboardRequest(BaseModel):
    """Intake for client onboarding + planning (drives the hybrid run)."""

    client_id: str = Field(min_length=1)
    segment: Segment
    name: str = Field(min_length=1)


class RebalanceRequest(BaseModel):
    """Intake for a discretionary rebalance (suitability-gated, consequential)."""

    client_id: str = Field(min_length=1)
    proposed_risk: float = Field(ge=0.0, le=1.0)


class CreditRequest(BaseModel):
    """Intake for a Lombard/credit facility (credit-gated, consequential)."""

    client_id: str = Field(min_length=1)
    loan_amount: float = Field(gt=0.0)
    facility: Facility


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str
