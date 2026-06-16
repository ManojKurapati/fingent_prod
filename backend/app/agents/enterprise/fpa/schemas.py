"""Typed request/response schemas for the FP&A group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    """Intake for a forecast/planning run (drives the hybrid fan-out)."""

    period: str = Field(min_length=1)
    cost_centres: list[str] = Field(min_length=1)
    variance_threshold: float = Field(default=0.1, ge=0.0)


class ScenarioRequest(BaseModel):
    """Intake for a standalone scenario/sensitivity run."""

    period: str = Field(min_length=1)
    cost_centres: list[str] = Field(min_length=1)
    drivers: dict[str, float] = Field(default_factory=dict)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
