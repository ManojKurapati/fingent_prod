"""Typed request/response schemas for the Private Markets group-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AssetClass = Literal["pe_vc", "credit", "real_asset", "fund_of_funds"]


class DealRequest(BaseModel):
    """Intake for an underwriting run (drives the hybrid diligence fan-out)."""

    deal_id: str = Field(min_length=1)
    asset_class: AssetClass
    sponsor: str = Field(min_length=1)


class MonitorRequest(BaseModel):
    """Intake for the standalone portfolio-stewardship monitor."""

    portfolio_id: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing a background job."""

    job_id: str
