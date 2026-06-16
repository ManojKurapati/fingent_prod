"""Typed request/response schemas for the Retail & Commercial Banking group-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["personal", "commercial", "branch"]


class ApplicationRequest(BaseModel):
    """Intake for a loan application (drives the sequential lending pipeline)."""

    application_id: str = Field(min_length=1)
    channel: Channel
    applicant: str = Field(min_length=1)
    loan_amount: float = Field(gt=0.0)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
