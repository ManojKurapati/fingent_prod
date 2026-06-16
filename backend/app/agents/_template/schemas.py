"""Typed request/response schemas for the template group-agent.

COPY THIS FILE. Replace the fields with your group's real intake/result shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Intake for a template run."""

    cost_centres: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
