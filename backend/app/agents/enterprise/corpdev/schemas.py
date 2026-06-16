"""Typed request/response schemas for the Corp Dev & Strategy group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DealRequest(BaseModel):
    """Intake for a deal-evaluation run (drives the hybrid deal spine)."""

    targets: list[str] = Field(min_length=1)
    synergy_rate: float = Field(default=0.1, ge=0.0)
    ebitda_multiple: float = Field(default=8.0, gt=0.0)


class EarningsPackRequest(BaseModel):
    """Intake for the standalone standing/IR path (strategy ‖ investor-relations)."""

    period: str = Field(min_length=1)
    segments: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
