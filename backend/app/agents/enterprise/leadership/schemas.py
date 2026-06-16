"""Typed request/response schemas for the Leadership group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BoardPackRequest(BaseModel):
    """Intake for a board-pack run (drives the hybrid synthesis fan-out)."""

    period: str = Field(min_length=1)
    divisions: list[str] = Field(min_length=1)
    target_leverage: float = Field(default=0.4, ge=0.0, le=1.0)


class CapitalScenarioRequest(BaseModel):
    """Intake for a standalone capital-structure scenario run."""

    period: str = Field(min_length=1)
    divisions: list[str] = Field(min_length=1)
    target_leverage: float = Field(default=0.4, ge=0.0, le=1.0)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
