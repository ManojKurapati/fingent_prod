"""Typed request/response schemas for the Transactional group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CycleRequest(BaseModel):
    """Intake for a full operational-cycle run (the hybrid lane fan-out)."""

    period: str = Field(min_length=1)
    vendors: list[str] = Field(min_length=1)
    customers: list[str] = Field(min_length=1)
    employees: list[str] = Field(default_factory=list)


class PaymentRunRequest(BaseModel):
    """Intake for a standalone AP payment run (pure parallel per-vendor match)."""

    period: str = Field(min_length=1)
    vendors: list[str] = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
