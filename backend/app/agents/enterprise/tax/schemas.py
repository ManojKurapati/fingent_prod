"""Typed request/response schemas for the Tax group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProvisionRequest(BaseModel):
    """Intake for a provision run (the hybrid per-jurisdiction fan-out)."""

    period: str = Field(min_length=1)
    jurisdictions: list[str] = Field(min_length=1)


class FileRequest(BaseModel):
    """Intake for a gated external filing (``return_id`` comes from the path)."""

    return_id: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
