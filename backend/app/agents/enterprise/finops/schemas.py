"""Typed request/response schemas for the Finance Systems & Operations group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OperationsRequest(BaseModel):
    """Intake for the operations run (the hybrid pipeline + parallel lanes)."""

    period: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)
    access_changes: list[str] = Field(default_factory=list)


class AccessChangeRequest(BaseModel):
    """Intake for a standalone ERP access/config change (SoD-gated)."""

    change: str = Field(min_length=1)
    role: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
