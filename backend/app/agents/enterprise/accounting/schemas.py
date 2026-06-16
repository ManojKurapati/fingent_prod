"""Typed request/response schemas for the Accounting & Controllership agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CloseRequest(BaseModel):
    """Intake for a period-close run (drives the hybrid sub-ledger fan-out)."""

    period: str = Field(min_length=1)
    entities: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
