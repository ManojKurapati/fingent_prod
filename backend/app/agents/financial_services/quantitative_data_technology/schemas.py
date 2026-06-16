"""Typed request/response schemas for the Quant/Data/Tech group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuantJobsRequest(BaseModel):
    """Intake for the parallel research/calibration fan-out."""

    dataset: str = Field(min_length=1)


class PromoteRequest(BaseModel):
    """Intake for promoting a candidate model/strategy to production.

    ``validation_token`` is the independent model-validation token issued by the
    Risk Agent; promotion is blocked unless it is present and approved.
    """

    model_id: str = Field(min_length=1)
    validation_token: str | None = None


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
