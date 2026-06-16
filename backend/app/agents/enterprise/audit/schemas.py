"""Typed request/response schemas for the Internal Audit & Controls group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EngagementRequest(BaseModel):
    """Intake for a risk-based audit engagement (drives the sequenced run)."""

    engagement: str = Field(min_length=1)
    controls: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
