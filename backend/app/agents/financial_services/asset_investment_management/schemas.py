"""Typed request/response schemas for the Asset & Investment Management agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RebalanceRequest(BaseModel):
    """Intake for a hybrid rebalance run (macro spine ‖ research fan-out)."""

    portfolio_id: str = Field(min_length=1)
    names: list[str] = Field(min_length=1)
    period: str = Field(default="FY26", min_length=1)


class ResearchRequest(BaseModel):
    """Intake for the standalone parallel research fan-out."""

    names: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
