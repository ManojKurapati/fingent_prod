"""Typed request/response schemas for the Operations group-agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TradeProcessRequest(BaseModel):
    """Intake for the confirm -> settle -> reconcile pipeline (one trade)."""

    trade_id: str = Field(min_length=1)
    amount: float = Field(gt=0.0)


class OpsReconRequest(BaseModel):
    """Intake for a standalone parallel reconciliation run over settled records."""

    as_of: str = Field(min_length=1)


class RunAccepted(BaseModel):
    """Returned immediately after enqueuing the background job."""

    job_id: str
