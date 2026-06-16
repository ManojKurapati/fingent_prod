"""Typed request/response schemas for the Sales & Trading / Markets group-agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["buy", "sell"]


class OrderRequest(BaseModel):
    """Intake for a client/flow order (drives the hybrid feeds->gate->route flow)."""

    order_id: str = Field(min_length=1)
    account: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    side: Side
    quantity: float = Field(gt=0.0)
    book: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
