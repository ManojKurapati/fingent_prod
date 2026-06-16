"""Typed request/response schemas for the Product/Strategy/Client group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InitiativeRequest(BaseModel):
    """Intake for the discovery -> pricing -> filing-gate -> launch chain.

    ``filing_token`` is the compliance/regulatory-filing clearance token; launch
    is blocked unless it is present and cleared.
    """

    name: str = Field(min_length=1)
    filing_token: str | None = None


class CommercialRequest(BaseModel):
    """Intake for the post-launch parallel commercial loop (per client).

    ``kyc_token`` is the KYC clearance token; client activation is blocked unless
    it is present and cleared.
    """

    client_id: str = Field(min_length=1)
    kyc_token: str | None = None


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
