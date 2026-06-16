"""Typed request/response schemas for the Investment Banking group-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DealType = Literal["ma", "ecm", "dcm", "levfin", "restructuring"]


class MandateRequest(BaseModel):
    """Intake for a deal mandate (drives the hybrid origination->execution flow)."""

    deal_id: str = Field(min_length=1)
    client: str = Field(min_length=1)
    deal_type: DealType
    sector: str = Field(default="generalist", min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
