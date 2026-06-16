"""FastAPI router for the Sales & Trading / Markets group-agent (auto-discovered).

* ``POST /agents/sales-trading-markets/orders`` — validate an order and enqueue the
  hybrid desk run; returns a ``job_id`` immediately. The pre-trade risk gate runs
  in the worker; order routing surfaces in the shared ``GET /approvals`` queue (and
  is withheld entirely when the gate denies).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.financial_services.sales_trading_markets.schemas import OrderRequest, RunAccepted
from app.agents.financial_services.sales_trading_markets.service import JOB_KIND_ORDER, register
from app.api.context import AppContext, get_context

router = APIRouter(prefix="/agents/sales-trading-markets", tags=["sales-trading-markets"])

Ctx = Annotated[AppContext, Depends(get_context)]


@router.post("/orders", response_model=RunAccepted)
async def submit_order(request: OrderRequest, ctx: Ctx) -> RunAccepted:
    register(ctx)  # idempotent; production registers once at startup instead
    job = await ctx.jobs.enqueue(
        JOB_KIND_ORDER, request.model_dump(), idempotency_key=f"stm.order:{request.order_id}"
    )
    return RunAccepted(job_id=job.id)
